#!/bin/bash

let "a = 0"
while [[ "$(squeue | grep $JOB_PID)" != "" ]]
do
  if [[ $((a % 5)) == 0 ]]; then
    squeue -l
    squeue -l --start
  fi

  cat $JOB_WORKDIR/output/*_out.txt | tail -n 15
  echo "Still running..."
  sleep 60
  let "a = a + 1"
done
