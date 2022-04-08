
import json
from os import path
import sys
import logging
from datetime import datetime
from jsonpath_ng import parse
from plumbum import local
import argparse
import yaml
from checks import *
from jinja2 import Environment, select_autoescape, FileSystemLoader

def getServer():
  currentContext = {}
  server = ""
  try:
    oc = local['oc']
    data = json.loads(oc('config', 'view', '-o', 'json'))
    for context in data['contexts']:
      if context['name'] == data['current-context']:
        currentContext = context['context']
        break
      #end
    #end

    for cluster in data['clusters']:
      if cluster['name'] == currentContext['cluster']:
        server = cluster['cluster']['server']
        break
      #end
    #end
  except:
    logging.error("unable to determine server name")
  #end

  return server
#end

def getObjects(type, namespace='default'):
  try: 
    oc = local["oc"]
    data = json.loads(oc('get', type, '-n', namespace, '-o', 'json'))
    logging.info("read objects data of type " + type)
  except:
    logging.error("unable to read object data of type " + type + " from namespace " + namespace)
    return []

  if "items" in data.keys():
    logging.info("read " + str(len(data['items'])) + " objects of type " + type + " from namespace " + namespace)
    return data["items"]

  logging.info("didn't find any objects of type " + type + " in namespace " + namespace)
  return []
#end

def getImageStreamSize(namespace='default'):
  totalSize = 0
  oc = local["oc"]
  imagestreams = json.loads(oc('get', 'imagestreams', '-n', namespace, '-o', 'json'))
  logging.info("Number of image streams: " + str(len(imagestreams['items'])))

# Loop through the ImageStreams
  # Initialize a dictionary of layers for this ImageStream
  # Get the raw json of the ImageStream
  # Parse out the list of tags
  # Loop through the ImageStreamTags
    # Initialize a dictionary of layers for this ImageStreamTag
    # If the image has no tags, break out
  imageLayers = {}
  for imagestream in imagestreams['items']:
    name = imagestream['metadata']['name']
    imagestream = json.loads(oc('get', f'--raw=/apis/image.openshift.io/v1/namespaces/{namespace}/imagestreams/{name}'))
    if len(imagestream['status']['tags']) > 0:
      for tag in imagestream['status']['tags']:
        for item in tag['items']:
          image = item['image']
          imagestreamImages = (json.loads(oc('get', f'--raw=/apis/image.openshift.io/v1/namespaces/{namespace}/imagestreamimages/{name}@{image}')))
          for dockerImageLayer in imagestreamImages['image']['dockerImageLayers']:
            imageLayers[dockerImageLayer['name']] = dockerImageLayer['size']

  for imageLayerSize in imageLayers.values():
    totalSize +=  float(imageLayerSize)
    
  logging.info('TOTAL IMAGESTREAM SIZE: ' + str(totalSize / 1024000) + ' MB.')

  return totalSize
#end

def checkForJenkins():
  podsWithJenkins = []
  logging.info('Namespace includes -tools. Checking for Jenkins pods...')
  oc = local["oc"]
  pods = oc('get', 'pods', '-o', 'custom-columns=POD:.metadata.name', '--no-headers')
  
  for pod in  pods.split():
    podDescription = oc('get', 'pod', pod)
    if 'jenkins' in podDescription:
      podDescription = json.loads(oc('get', 'pod', pod, '-o', 'json'))
      logging.info('Found Jenkins pod: ' + pod)
      podResources = podDescription['spec']['containers'][0]['resources']
      jenkinsPod  = {
        'name': pod,
        'cpuLimit': podResources['limits']['cpu'],
        'cpuLimitMeetsBP':  compareValuesForBestPractice(podResources['limits']['cpu'], '1000m'),
        'memoryLimit': podResources['limits']['memory'],
        'memLimitMeetsBP': compareValuesForBestPractice(podResources['limits']['memory'], '2Gb', '1Gb'),
        'cpuRequest': podResources['requests']['cpu'],
        'cpuReqMeetsBP': compareValuesForBestPractice(podResources['requests']['cpu'], '100m'),
        'memoryRequest': podResources['requests']['memory'],
        'memReqMeestBP': compareValuesForBestPractice(podResources['requests']['memory'],  '512m')
      }
      podsWithJenkins.append(jenkinsPod)   
  return podsWithJenkins
#end

def compareValuesForBestPractice(val, recommended, lower = -1):
  lowerAsNumber = -1
  if lower != -1:
    numeric_filter = filter(str.isdigit, lower)
    lowerAsNumber = int("".join(numeric_filter))
    if  'gb' in str.lower(lower):
      lowerAsNumber *= 1000
    numeric_filter = filter(str.isdigit, val)
    valAsNumber = int("".join(numeric_filter))
    if  'gb' in str.lower(val):
      valAsNumber *= 1000
    numeric_filter = filter(str.isdigit, recommended)
    recommendedAsNumber = int("".join(numeric_filter))
    if  'gb' in str.lower(recommended):
      recommendedAsNumber *= 1000

    return val <= recommended and val >= lower
  
  else:
    return str.lower(val) == str.lower(recommended)

#end

def hpaCheck(workloadData):
  requiredScaleTargetRef = {'kind': workloadData['kind'], 'name': workloadData['metadata']['name']}
  retval = {'status': 'fail', 'text': "unable to find an HPA with the following scaleTargetRef:\n" + yaml.dump(requiredScaleTargetRef)}
  jsonpath_expr = parse('spec.scaleTargetRef')
  for hpa in hpaObjects:
    if retval['status'] == 'pass':
      break
    #end

    matches = jsonpath_expr.find(hpa)
    for match in matches:
      try: 
        if (match.value['kind'] == workloadData['kind']) and (match.value['name'] == workloadData['metadata']['name']):
          retval['status'] = 'pass'
          retval['text'] = yaml.dump(match.value)
          break
        #end
      except:
        pass
      #end
    #end
  #end

  return retval
#end

def pdbCheck(workloadData):
  retval = {'status': 'fail', 'text': "unable to find a matching PDB.  Make sure that spec.selector.matchLabels is defined and that there is a corresponding PDB."}
  jsonpath_expr = parse('spec.selector.matchLabels')
  for pdb in pdbObjects:
    if retval['status'] == 'pass':
      break
    #end

    matches = jsonpath_expr.find(pdb)
    for match in matches:
      try: 
        if (match.value == workloadData['spec']['selector']['matchLabels']):
          retval['status'] = 'pass'
          retval['text'] = yaml.dump(match.value)
          break
        #end
      except:
        pass
      #end
    #end
  #end

  return retval
#end

def writeReport(filename, results, namespace, checksInfo, clusterName, podsWithFailedChecks):
  workloadNames = results[next(iter(results))].keys()
  file = open(filename, 'w')
  imagestreamSize = getImageStreamSize(namespace)
  jenkinsPods = []
  if '-tools' in namespace:
    jenkinsPods = checkForJenkins()

    #check for Jenkins in tools namespace
  env = Environment(
    autoescape=select_autoescape(),
    loader=FileSystemLoader(path.join(path.dirname(__file__), 'templates'))
  )
  template = env.get_template("reportTemplate.html.j2")
  file.write(template.render(
    datetime = datetime.now().strftime("%Y-%m-%d-%H:%M:%S"),
    clusterName = clusterName,
    namespace = namespace,
    workloadNames = workloadNames,
    results = results,
    checksInfo = checksInfo,
    podsWithFailedChecks = podsWithFailedChecks,
    imagestreams = getObjects('imagestreams', namespace),
    imagestreamSize = str(round(float(imagestreamSize / 1024000), 2)),
    jenkinsPods = jenkinsPods
  ))
  file.close()
#end


parser = argparse.ArgumentParser()
parser.add_argument("-l", help="log file name", type=str, default="-")
parser.add_argument("-o", help="output file name", type=str, default="report.html")
parser.add_argument('-n', help="namespace", type=str, default="default")
parser.add_argument('-c', help="cluster name", type=str, default="silver")
args = parser.parse_args()

logstream = None
if args.l == '-':
  logstream = sys.stdout
else:
  logstream = open(args.l, 'a')

logging.basicConfig(stream=logstream, level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d-%H:%M:%S')
logging.info("generating report")

namespace = args.n
clusterName = args.c
serverName = getServer()

workloadObjects = getObjects('cronjobs', namespace) + getObjects('daemonset', namespace) + getObjects('deployment', namespace) + getObjects('statefulset', namespace) + getObjects('deploymentconfig', namespace)
if len(workloadObjects) == 0:
  message = "unable to find any cronjobs, daemonsets, deployments, statefulsets or deploymentconfigs in namespace " + namespace + ".  Report not generated"
  logging.info(message)
  print(message)
  sys.exit()
#end

hpaObjects = getObjects('hpa', namespace)
pdbObjects = getObjects('poddisruptionbudgets', namespace)
checks = {}
checks["declarativeComponentCheck"] = declarativeComponentCheck
#checks["RollingUpdateCheck"] = rollingUpdateCheck #not our business to tell people how to update (best practice for stateless)
checks["ResourceUtilizationHeader"] = resourceUtilizationHeader
checks["CPURequestCheck"] = cpuRequestCheck
checks["MemoryRequestCheck"] = memoryRequestCheck
checks["CPULimitCheck"] = cpuLimitCheck
checks["CPULimitRequestRatio"] = cpuLimitRequestRatio
checks["MemoryLimitCheck"] = memoryLimitCheck
#probes
checks["ProbeHeader"] = probeHeader
checks["LivenessProbeCheck"] = livenessProbeCheck
checks["ReadinessProbeCheck"] = readinessProbeCheck
#checks["StatelessCheck"] = statelessCheck #lots of apps are not stateless, and presenting a warning everytime there is a persistent volume is not appropriate
#checks["HPACheck"] = hpaCheck   #Not always needed, and if it is, we need to know more about what we're trying to say is good or bad
#checks["PDBCheck"] = pdbCheck   #pdbCheck is not always needed, and if it's needed, make sure we're not creating 'no disruption scenarios'
#pdb and hpa checks are attainable with some extra work

cronjobChecks = {}
cronjobChecks["declarativeComponentCheck"] = declarativeComponentCheck
#cronjobChecks["RollingUpdateCheck"] = notApplicableCheck
cronjobChecks["ResourceUtilizationHeader"] = resourceUtilizationHeader
cronjobChecks["CPURequestCheck"] = cronjobCpuRequestCheck
cronjobChecks["MemoryRequestCheck"] = cronjobMemoryRequestCheck
cronjobChecks["CPULimitCheck"] = cronjobCpuLimitCheck
cronjobChecks["MemoryLimitCheck"] = cronjobMemoryLimitCheck
cronjobChecks["CPULimitRequestRatio"]  = cronjobCpuLimitRequestRatio
cronjobChecks["ProbeHeader"] = probeHeader
cronjobChecks["LivenessProbeCheck"] = notApplicableCheck
cronjobChecks["ReadinessProbeCheck"] = notApplicableCheck
#cronjobChecks["StatelessCheck"] = notApplicableCheck
#cronjobChecks["HPACheck"] = notApplicableCheck
#cronjobChecks["PDBCheck"] = notApplicableCheck

checksInfo = {
  "declarativeComponentCheck" : {
    "title" : "A declarative approach to deploy the workload using either a Deployment(Config), StatefulSet, DaemonSet, or CronJob.",
    "href" : "https://docs.openshift.com/container-platform/4.9/applications/deployments/what-deployments-are.html"
  },
  "RollingUpdateCheck" : {
    "title" : "A rolling deployment slowly replaces instances of the previous version of an application with instances of the new version of the application. The rolling strategy is the default deployment strategy used if no strategy is specified on a DeploymentConfig object.",
    "href" : "https://docs.openshift.com/container-platform/4.9/applications/deployments/deployment-strategies.html#deployments-rolling-strategy_deployment-strategies"
  },
  "CPURequestCheck" : {
    "title" : "The CPU request represents a minimum amount of CPU that your container may consume, but if there is no contention for CPU, it can use all available CPU on the node. If there is CPU contention on the node, CPU requests provide a relative weight across all containers on the system for how much CPU time the container may use.",
    "href" : "https://docs.openshift.com/online/pro/dev_guide/compute_resources.html#dev-cpu-requests"
  },
  "MemoryRequestCheck" : {
    "title" : "By default, a container is able to consume as much memory on the node as possible. In order to improve placement of pods in the cluster, specify the amount of memory required for a container to run. The scheduler will then take available node memory capacity into account prior to binding your pod to a node. A container is still able to consume as much memory on the node as possible even when specifying a request.",
    "href" : "https://docs.openshift.com/online/pro/dev_guide/compute_resources.html#dev-memory-requests"
  },
  "CPULimitCheck" : {
    "title" : "Each container in a pod can specify the amount of CPU it is limited to use on a node. CPU limits control the maximum amount of CPU that your container may use independent of contention on the node. If a container attempts to exceed the specified limit, the system will throttle the container. This allows the container to have a consistent level of service independent of the number of pods scheduled to the node.",
    "href" : "https://docs.openshift.com/online/pro/dev_guide/compute_resources.html#dev-cpu-limits"
  },
  "MemoryLimitCheck" : {
    "title" : "If you specify a memory limit, you can constrain the amount of memory the container can use. For example, if you specify a limit of 200Mi, a container will be limited to using that amount of memory on the node. If the container exceeds the specified memory limit, it will be terminated and potentially restarted dependent upon the container restart policy.",
    "href" : "https://docs.openshift.com/online/pro/dev_guide/compute_resources.html#dev-memory-limits"
  },
  "LivenessProbeCheck" : {
    "title" : "A liveness probe determines if a container is still running. If the liveness probe fails due to a condition such as a deadlock, the kubelet kills the container. The pod then responds based on its restart policy.",
    "href" : "https://docs.openshift.com/container-platform/4.9/applications/application-health.html#application-health-about_application-health"
  },
  "ReadinessProbeCheck" : {
    "title" : "A readiness probe determines if a container is ready to accept service requests. If the readiness probe fails for a container, the kubelet removes the pod from the list of available service endpoints.",
    "href" : "https://docs.openshift.com/container-platform/4.9/applications/application-health.html#application-health-about_application-health"
  },
  "StatelessCheck" : {
    "title" : "A stateless workload should not have PersistentVolumeClaims.",
    "href" : "https://docs.openshift.com/container-platform/4.9/storage/understanding-persistent-storage.html"
  },
  "HPACheck" : {
    "title" : "As a developer, you can use a horizontal pod autoscaler (HPA) to specify how OpenShift Container Platform should automatically increase or decrease the scale of a replication controller or deployment configuration, based on metrics collected from the pods that belong to that replication controller or deployment configuration.",
    "href" : "https://docs.openshift.com/container-platform/4.9/nodes/pods/nodes-pods-autoscaling.html"
  },
  "PDBCheck" : {
    "title" : "A pod disruption budget is part of the Kubernetes API, which can be managed with oc commands like other object types. They allow the specification of safety constraints on pods during operations, such as draining a node for maintenance.",
    "href" : "https://docs.openshift.com/container-platform/4.9/nodes/pods/nodes-pods-configuring.html#nodes-pods-configuring-pod-distruption-about_nodes-pods-configuring"
  },
  "CPULimitRequestRatio" : {
    "title" : "A 3:1 ratio or less of CPU Limit over Request is prefered where the requested CPU amount is the minimum of what your application needs. It may be appropriate to decrease the ratio based on what stage of development your application is in.",
    "href" : "https://developer.gov.bc.ca/Resource-Tuning-Recommendations#setting-requests-and-limits"
  },
  "ProbeHeader" : {
  },
  "ResourceUtilizationHeader" : {
  }
}

results = {}
podsWithFailedChecks = []
for checkName in checks.keys():
  results[checkName] = {}
  for workload in workloadObjects:
    workloadName = workload['metadata']['name']
    logging.info("running check " + checkName + " on workload " + workloadName)
    if workload['kind'] == 'CronJob':
      results[checkName][workloadName] = cronjobChecks[checkName](workload)
    else:
      results[checkName][workloadName] = checks[checkName](workload)
    if results[checkName][workloadName]['status'] != 'pass' and not podsWithFailedChecks.__contains__(workloadName):
      podsWithFailedChecks.append(workloadName)

writeReport(args.o, results, namespace, checksInfo, clusterName, podsWithFailedChecks)
