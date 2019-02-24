#!/bin/bash

cp /usr/src/grin/bitgrin-server.toml /server/bitgrin-server.toml
cd /server
echo "Backup Chain Data"
tar czf grin.backup.$(date "+%F-%T" |tr : '_').tgz .grin
echo "Start Bitgrin Server"
bitgrin server run
