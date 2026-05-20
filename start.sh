#!/bin/bash
# MAM16 Robot indítópult

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTCODE="$SCRIPT_DIR/BotCode"
PY="python3.8"

C_CYAN='\033[0;36m'
C_YELLOW='\033[1;33m'
C_GREEN='\033[0;32m'
C_GRAY='\033[0;90m'
C_BOLD='\033[1m'
C_OFF='\033[0m'

header() {
    clear
    echo -e "${C_CYAN}"
    echo "   ███╗   ███╗ █████╗ ███╗   ███╗ ██╗ ██████╗ "
    echo "   ████╗ ████║██╔══██╗████╗ ████║███║██╔════╝ "
    echo "   ██╔████╔██║███████║██╔████╔██║╚██║███████╗ "
    echo "   ██║╚██╔╝██║██╔══██║██║╚██╔╝██║ ██║██╔═══██╗"
    echo "   ██║ ╚═╝ ██║██║  ██║██║ ╚═╝ ██║ ██║╚██████╔╝"
    echo "   ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝ ╚═╝ ╚═════╝ "
    echo -e "${C_OFF}"
    echo -e "   ${C_YELLOW}Magyarok a Marson — Robot indítópult${C_OFF}"
    echo ""
}

# GPU-mód almenü, majd indítás
# $1 = leírás, $2 = python argumentumok
launch_menu() {
    local label="$1"
    local args="$2"

    header
    echo -e "   ${C_BOLD}$label${C_OFF}"
    echo ""
    echo -e "   ${C_CYAN}Feldolgozási mód:${C_OFF}"
    echo "     1) GPU — CUDA (ha elérhető)"
    echo "     2) CPU — csak processzor"
    echo "     b) Vissza"
    echo ""
    read -rp "   Választás: " m
    echo ""

    case "$m" in
        1)
            unset CUDA_VISIBLE_DEVICES
            echo -e "   ${C_GREEN}Indítás: $PY $args  [GPU mód]${C_OFF}"
            echo ""
            cd "$BOTCODE" && $PY $args
            ;;
        2)
            export CUDA_VISIBLE_DEVICES=""
            echo -e "   ${C_GREEN}Indítás: $PY $args  [CPU mód]${C_OFF}"
            echo ""
            cd "$BOTCODE" && $PY $args
            unset CUDA_VISIBLE_DEVICES
            ;;
        b|B)
            return
            ;;
        *)
            echo -e "   ${C_GRAY}Érvénytelen választás.${C_OFF}"
            sleep 1
            ;;
    esac

    echo ""
    read -rp "   Nyomj Entert a főmenühöz..." _
}

# Főmenü
while true; do
    header
    echo -e "   ${C_BOLD}Indítási mód:${C_OFF}"
    echo ""
    echo "     1) Normál indítás"
    echo "     2) Teszt UI-s indítás          (--test-ui)"
    echo "     3) Teszt UI + dry-run          (--test-ui --dry-run)"
    echo ""
    echo -e "     ${C_GRAY}q) Kilépés${C_OFF}"
    echo ""
    read -rp "   Választás: " choice

    case "$choice" in
        1) launch_menu "Normál indítás" "main.py" ;;
        2) launch_menu "Teszt UI-s indítás" "main.py --test-ui" ;;
        3) launch_menu "Teszt UI + dry-run" "main.py --test-ui --dry-run" ;;
        q|Q)
            echo ""
            echo -e "   ${C_GRAY}Viszlát!${C_OFF}"
            echo ""
            exit 0
            ;;
        *)
            echo -e "   ${C_GRAY}Érvénytelen választás.${C_OFF}"
            sleep 1
            ;;
    esac
done
