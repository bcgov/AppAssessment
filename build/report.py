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

def writeReport(filename, results, serverName, namespace):
  file = open(filename, 'w')
  file.write("<html>\n<head>\n")
  file.write('<link href="https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/4.1.3/css/bootstrap-reboot.min.css" rel="stylesheet">' + "\n")
  file.write('<link href="https://fonts.googleapis.com/css?family=Noto+Sans" rel="stylesheet">' + "\n")
  file.write('<link rel="stylesheet" href="style.css">' + "\n")
  file.write("<style>\ntable, th, td {\n  border: 1px solid black;\n}\n</style>\n")
  file.write("<title>report generated on " + datetime.now().strftime("%Y-%m-%d-%H:%M:%S") + "</title>\n</head>\n<body>\n")
  file.write("<header>\n" + '<div class="banner">' + "\n" + '<a href="https://gov.bc.ca">' + "\n")
  file.write('<img src="https://developer.gov.bc.ca/static/BCID_H_rgb_rev-20eebe74aef7d92e02732a18b6aa6bbb.svg" alt="Go to the Government of British Columbia website" height="50px"/>' + "\n")
  file.write("</a>\n<h1>Hello British Columbia</h1>\n</div>\n" + '<div class="other">' + "\n" + '&nbsp;' + "\n</div>\n</header>\n" + '<p style="padding-top:50px"></p>' + "\n")
  file.write("<h1>Workload health check report for namespace " + namespace + " on server " + serverName + "\n<hr>\n<table>\n")

  workloadNames = results[next(iter(results))].keys()
  file.write("<tr>\n<td>Target</td>")
  for workloadName in workloadNames:
    file.write("<td>" + workloadName + "</td>")
  file.write("\n</tr>\n")

  for checkName in results.keys():
    file.write("<tr>\n<td>"+checkName+"</td>")
    for workloadName in results[checkName].keys():
      file.write("<td style=\"background-color: " + results[checkName][workloadName]['color'] + "\"></td>")

    file.write("\n</tr>\n")
  #end

  file.write("</table>\n<hr>\n")

  for workloadName in workloadNames:
    file.write("<table>\n<tr><td>Target</td><td>" + workloadName + "</td></tr>\n")

    for checkName in results.keys():
      file.write("<tr><td>"+checkName+"</td><td style=\"background-color: " + results[checkName][workloadName]['color'] + "\"><pre>" + results[checkName][workloadName]['text'] + "</pre></td></tr>\n")
    #end

    file.write("</table>\n<hr>\n")
  #end

  file.write('<footer class="footer">' + "\n" + '<div class="container">' + "\n<ul>\n" + '<li><a href=".">Home</a></li>' + "\n" + '<li><a href=".">Disclaimer</a></li>' + "\n")
  file.write('<li><a href=".">Privacy</a></li>' + "\n" + '<li><a href=".">Accessibility</a></li>' + "\n" + '<li><a href=".">Copyright</a></li>' + "\n")
  file.write('<li><a href=".">Contact Us</a></li>' + "\n</ul>\n</div>\n</footer>\n</body>\n</html>\n")
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

writeReport(args.o, results, serverName, namespace)
