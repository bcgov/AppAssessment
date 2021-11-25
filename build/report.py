import json
from os import write
import sys
import logging
from datetime import datetime
from jsonpath_ng import jsonpath, parse
from plumbum import local
import argparse
import yaml
from checks import *
from jinja2 import Environment, PackageLoader, select_autoescape

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

def hpaCheck(workloadData):
  requiredScaleTargetRef = {'kind': workloadData['kind'], 'name': workloadData['metadata']['name']}
  retval = {'color': 'red', 'text': "unable to find an HPA with the following scaleTargetRef:\n" + yaml.dump(requiredScaleTargetRef)}
  jsonpath_expr = parse('spec.scaleTargetRef')
  for hpa in hpaObjects:
    if retval['color'] == 'green':
      break
    #end

    matches = jsonpath_expr.find(hpa)
    for match in matches:
      try: 
        if (match.value['kind'] == workloadData['kind']) and (match.value['name'] == workloadData['metadata']['name']):
          retval['color'] = 'green'
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
  retval = {'color': 'red', 'text': "unable to find a matching PDB.  Make sur that spec.selector.matchLabels is defined and that there is a corresponding PDB."}
  jsonpath_expr = parse('spec.selector.matchLabels')
  for pdb in pdbObjects:
    if retval['color'] == 'green':
      break
    #end

    matches = jsonpath_expr.find(pdb)
    for match in matches:
      try: 
        if (match.value == workloadData['spec']['selector']['matchLabels']):
          retval['color'] = 'green'
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

def writeReport(filename, results, serverName, namespace, checksInfo):
  workloadNames = results[next(iter(results))].keys()
  file = open(filename, 'w')
  
  env = Environment(
    loader=PackageLoader("report"),
    autoescape=select_autoescape()
  )
  template = env.get_template("reportTemplate.html.j2")
  file.write(template.render(
    datetime = datetime.now().strftime("%Y-%m-%d-%H:%M:%S"),
    namespace = namespace,
    serverName = serverName,
    workloadNames = workloadNames,
    results = results,
    checksInfo = checksInfo
  ))
  file.close()
#end


parser = argparse.ArgumentParser()
parser.add_argument("-l", help="log file name", type=str, default="-")
parser.add_argument("-o", help="output file name", type=str, default="report.html")
parser.add_argument('-n', help="namespace", type=str, default="default")
args = parser.parse_args()

logstream = None
if args.l == '-':
  logstream = sys.stdout
else:
  logstream = open(args.l, 'a')

logging.basicConfig(stream=logstream, level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d-%H:%M:%S')
logging.info("generating report")

namespace = args.n
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
checks["RollingUpdateCheck"] = rollingUpdateCheck
checks["CPURequestCheck"] = cpuRequestCheck
checks["MemoryRequestCheck"] = memoryRequestCheck
checks["CPULimitCheck"] = cpuLimitCheck
checks["MemoryLimitCheck"] = memoryLimitCheck
checks["LivenessProbeCheck"] = livenessProbeCheck
checks["ReadinessProbeCheck"] = readinessProbeCheck
checks["StatelessCheck"] = statelessCheck
checks["HPACheck"] = hpaCheck
checks["PDBCheck"] = pdbCheck

cronjobChecks = {}
cronjobChecks["declarativeComponentCheck"] = declarativeComponentCheck
cronjobChecks["RollingUpdateCheck"] = notApplicableCheck
cronjobChecks["CPURequestCheck"] = cronjobCpuRequestCheck
cronjobChecks["MemoryRequestCheck"] = cronjobMemoryRequestCheck
cronjobChecks["CPULimitCheck"] = cronjobCpuLimitCheck
cronjobChecks["MemoryLimitCheck"] = cronjobMemoryLimitCheck
cronjobChecks["LivenessProbeCheck"] = notApplicableCheck
cronjobChecks["ReadinessProbeCheck"] = notApplicableCheck
cronjobChecks["StatelessCheck"] = notApplicableCheck
cronjobChecks["HPACheck"] = notApplicableCheck
cronjobChecks["PDBCheck"] = notApplicableCheck

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
  }
}

results = {}
for checkName in checks.keys():
  results[checkName] = {}
  for workload in workloadObjects:
    workloadName = workload['metadata']['name']
    logging.info("running check " + checkName + " on workload " + workloadName)
    if workload['kind'] == 'CronJob':
      results[checkName][workloadName] = cronjobChecks[checkName](workload)
    else:
      results[checkName][workloadName] = checks[checkName](workload)

writeReport(args.o, results, serverName, namespace, checksInfo)
