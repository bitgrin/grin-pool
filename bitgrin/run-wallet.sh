#!/bin/bash -x


# Live here
cd /wallet

# Copy in updated config
cp /usr/src/grin/bitgrin-wallet.toml /wallet/bitgrin-wallet.toml

# Create new wallet if none exists
if [ ! -f /wallet/wallet_data/wallet.seed ]; then
    echo ${WALLET_PASSWORD} > /password.txt
    echo ${WALLET_PASSWORD} >> /password.txt
    bitgrin ${NET_FLAG} wallet init < /password.txt
    rm /password.txt
fi

MODE="public"
if [ $# -ne 0 ]; then
    MODE=$1
fi


if [ $MODE == "private" ]; then
    mkdir -p /root/.grin/
    echo ${WALLET_OWNER_API_PASSWORD} > /root/.grin/.api_secret
    chmod 600 /root/.grin/.api_secret
    echo "Waiting for public wallet to start"
    sleep 120 # Let the public wallet start first
    keybase login
    echo "Starting wallet owner_api"
    bitgrin ${NET_FLAG} wallet -p ${WALLET_PASSWORD} owner_api
else
    echo "Backup Wallet DB"
    tar czf wallet_db.backup.$(date "+%F-%T" |tr : '_').tgz wallet_data
    echo "Running wallet check"
    bitgrin ${NET_FLAG} wallet -p ${WALLET_PASSWORD} check
    echo "Starting public wallet listener"
    bitgrin ${NET_FLAG} wallet -p ${WALLET_PASSWORD} listen
fi
