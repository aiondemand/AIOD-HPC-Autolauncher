#!/bin/bash

let "a = 0"
while [[ "$(docker ps | grep $JOB_PID)" != "" ]]
do
  if [[ $((a % 5)) == 0 ]]; then
    docker ps | grep $JOB_PID
  fi

  cat $JOB_WORKDIR/output/*_out.txt | tail -n 15
  echo "Still running..."
  sleep 60
  let "a = a + 1"
done
