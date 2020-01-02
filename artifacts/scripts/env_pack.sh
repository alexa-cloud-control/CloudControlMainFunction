#! /bin/bash
mkdir ../package
cd ../airly/lib/python3.6/site-packages/
zip -g -r ../../../../package/CloudControlMainFunction.zip . 
cd ../../../../../py/
pwd && ls -al
zip -g ../artifact/package/CloudControlMainFunction.zip CloudControlMainFunction.py