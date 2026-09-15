#!/usr/bin/env bash
# Fake relay output for the demo recording (assets/shell/record.sh).
# One Dark Pro exact colors (24-bit true color)
RED='\033[38;2;224;108;117m'
GREEN='\033[38;2;152;195;121m'
YELLOW='\033[38;2;229;192;123m'
BLUE='\033[38;2;97;175;239m'
MAGENTA='\033[38;2;198;120;221m'
CYAN='\033[38;2;86;182;194m'
WHITE='\033[38;2;171;178;191m'
GRAY='\033[38;2;92;99;112m'
BOLD='\033[1m'
NC='\033[0m'

if [ "$1" = "--team" ]; then
  echo -e "${CYAN}[relay]${NC} ${WHITE}AI message:${NC} ${MAGENTA}feat(payments):${NC} ${WHITE}add transaction retry handling${NC}"
  printf "${YELLOW}[Yes] [Edit] [Retry] [No]${NC} ${GRAY}(y/e/r/n):${NC} "
  sleep 1.2
  echo -e "${GREEN}y${NC}"
  sleep 0.3
  echo -e "${GREEN}[relay] done:${NC} ${WHITE}pushed to${NC} ${BLUE}'feat/payments'${NC}"
elif [ "$1" = "pr" ]; then
  echo -e "${GREEN}[relay]${NC} ${WHITE}opened PR${NC} ${YELLOW}#42${NC}${WHITE}:${NC} ${BLUE}https://github.com/Fiqqar/Relay/pull/42${NC}"
fi
