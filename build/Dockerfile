FROM registry.access.redhat.com/ubi8/python-36:1-155
USER root
ADD ./report.py ./
ADD ./checks.py ./
ADD ./requirements.txt ./
ADD ./startup.sh ./
ADD ./static/style.css ./
ADD ./static/bootstrap-theme.min.css ./
ADD ./requirements.txt ./   


ENV HOME=/tmp/

RUN mkdir templates
ADD ./templates/reportTemplate.html.j2 ./templates
RUN pip install -r ./requirements.txt
# Install OC CLI
RUN curl https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/openshift-client-linux.tar.gz --output ./oc.tar.gz
RUN tar -xzf ./oc.tar.gz -C /usr/local/bin/
RUN chmod 755 /usr/local/bin/oc
RUN chmod 755 ./startup.sh
RUN chmod 755 /usr/share/nginx/html
USER 1001
CMD ["./startup.sh"]
