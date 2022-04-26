FROM ubuntu:20.04

RUN apt-get update
RUN DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get -y install tzdata
RUN apt-get install -y git cmake wget python3 python3-pip

RUN python3 -m pip install jupyter notebook

# requirements
ADD requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

# dev requirements
ADD deployment/dev-requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt

# app
WORKDIR /app

# entrypoint
ENTRYPOINT [ "/bin/python3" ]
