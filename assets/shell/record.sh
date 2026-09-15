#!/bin/bash
# Demo recorder: types the commands and plays back fake-relay.sh so the
# walkthrough can be captured to assets/relay-demo.gif.
# One Dark Pro prompt colors
GREEN='\033[38;2;152;195;121m'
BLUE='\033[38;2;97;175;239m'
NC='\033[0m'

typeit() {
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.04
  done
  echo
}

clear
sleep 0.3

printf "${GREEN}❯${NC} "
typeit "relay --team"
sleep 0.4
./fake-relay.sh --team
sleep 1.2

echo
printf "${GREEN}❯${NC} "
typeit "relay pr"
sleep 0.4
./fake-relay.sh pr
sleep 2
