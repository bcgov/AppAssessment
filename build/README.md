# Openshift workload reporting

## Preparation
This reporting tool was tested on Python 3.9.7, but it should work on any python 3.  To install the required libraries, run the following command:
```
pip install -r requirements.txt
```
Additionally, ensure that 'oc', the openshift client is installed.  This script was tested with version 4.6.3 of 'oc'.
Before running the script, ensure that an 'oc login' has been performed.  The script calls 'oc' to gather the necessary information.

## Running the script
Once the above requirements have been met, the script can be run with the following command:
```
python report.py <namespace>
```
The script accepts a namespace as an optional argument and will produce 2 files, report.html and report.log.  report.html is the output and report.log is a log file, which should be inspected for errors.
