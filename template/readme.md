## This is temporary! Templates should be consumed by CICD pipeline!

To run the network policy template: `oc process -f template/network-policy-ingress.yaml -p NAMESPACE=<namespace_name> | oc apply -f -`
