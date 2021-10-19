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
    logging.error("unable to read object data of type " + type)
    return []

  if "items" in data.keys():
    return data["items"]

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
  file.write("<html>\n")
  file.write("<head>\n")
  file.write("<style>\ntable, th, td {\n  border: 1px solid black;\n}\n</style>\n")
  file.write("<title>report generated on " + datetime.now().strftime("%Y-%m-%d-%H:%M:%S") + "</title>\n")
  file.write("</head>\n")
  file.write("<body>\n")

  file.write("<h1>Workload health check report for namespace " + namespace + " on server " + serverName + "\n")
  file.write("<hr>\n")
  file.write("<table>\n")

  workloadNames = results[next(iter(results))].keys()
  file.write("<tr>\n")
  file.write("<td>Target</td>")
  for workloadName in workloadNames:
    file.write("<td>" + workloadName + "</td>")
  file.write("\n</tr>\n")

  for checkName in results.keys():
    file.write("<tr>\n<td>"+checkName+"</td>")
    for workloadName in results[checkName].keys():
      file.write("<td style=\"background-color: " + results[checkName][workloadName]['color'] + "\"></td>")

    file.write("\n</tr>\n")
  #end

  file.write("</table>\n")
  file.write("<hr>\n")

  for workloadName in workloadNames:
    file.write("<table>\n")
    file.write("<tr><td>Target</td><td>" + workloadName + "</td></tr>\n")

    for checkName in results.keys():
      file.write("<tr><td>"+checkName+"</td><td style=\"background-color: " + results[checkName][workloadName]['color'] + "\"><pre>" + results[checkName][workloadName]['text'] + "</pre></td></tr>\n")

    file.write("</table>\n")
    file.write("<hr>\n")

  file.write("</body>\n")
  file.write("</html>\n")
  file.close()
#end


parser = argparse.ArgumentParser()
parser.add_argument("-l", help="log file name", type=str, default="report.log")
parser.add_argument("-o", help="output file name", type=str, default="report.html")
parser.add_argument('-n', help="namespace", type=str, default="default")
args = parser.parse_args()

logging.basicConfig(filename=args.l, level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d-%H:%M:%S')
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
