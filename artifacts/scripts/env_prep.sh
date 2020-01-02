#! /bin/bash

echo "Run virtualenv install"
./virtualenv.sh

if [ $? == 0 ]; then
  echo "Create zip package"
  ./env_pack.sh

else
  echo "Installation not successful"
  exit 1
fi