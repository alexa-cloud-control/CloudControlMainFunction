#! /bin/bash
mkdir ../package
cd ../cloudcontrol/lib/python3.6/site-packages/
zip -g -r ../../../../package/CloudControlMainFunction.zip . 
cd ../../../../../py/
pwd && ls -al
zip -g ../artifacts/package/CloudControlMainFunction.zip CloudControlMainFunction.py