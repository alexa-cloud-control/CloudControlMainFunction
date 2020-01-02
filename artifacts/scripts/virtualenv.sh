#! /bin/bash

virtualenv ../cloudcontrol -p python3.6
# create virtualenv called ansible with python3.6.

. ../cloudcontrol/bin/activate
#activate the virtualenv.

pip install -r ../requirements.txt
# install needed packages inside the virtualenv.