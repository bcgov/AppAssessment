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
python report.py -n <namespace> -o <filename> -l <logfilename>
```
The script accepts 3 optional arguments and will produce 2 files, the report file in html format and a log file.  The -n flag is used to specify a namespace to use.  If unspecified, the default namespace is used.  The -l flag is used to specify the name of the log file.  If unspecified, log messages are sent to standard output.  The -o flag is used to specify the filename of the resulting report.  If unspecified, 'report.html' is used.
