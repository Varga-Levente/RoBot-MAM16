#!/bin/bash
# MAM16 Robot indítópult

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOTCODE="$SCRIPT_DIR/BotCode"
PY="python3.8"
VIDEOS_DIR="$HOME/Videos"

C_CYAN='\033[0;36m'
C_YELLOW='\033[1;33m'
C_GREEN='\033[0;32m'
C_RED='\033[0;31m'
C_GRAY='\033[0;90m'
C_BOLD='\033[1m'
C_OFF='\033[0m'

header() {
    clear
    echo -e "${C_CYAN}"
    echo "   ██████╗  ██████╗ ██████╗  ██████╗ ████████╗"
    echo "   ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝"
    echo "   ██████╔╝██║   ██║██████╔╝██║   ██║   ██║   "
    echo "   ██╔══██╗██║   ██║██╔══██╗██║   ██║   ██║   "
    echo "   ██║  ██║╚██████╔╝██████╔╝╚██████╔╝   ██║   "
    echo "   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝   "
    echo -e "${C_OFF}"
    echo -e "   ${C_YELLOW}Magyarok a Marson — Robot indítópult${C_OFF}"
    echo ""
}

# ── GPU/CPU almenü + indítás ──────────────────────────────────────────────────
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
            echo -e "   ${C_GREEN}Indítás: $PY $args  [GPU]${C_OFF}"
            echo ""
            cd "$BOTCODE" && $PY $args
            ;;
        2)
            export CUDA_VISIBLE_DEVICES=""
            echo -e "   ${C_GREEN}Indítás: $PY $args  [CPU]${C_OFF}"
            echo ""
            cd "$BOTCODE" && $PY $args
            unset CUDA_VISIBLE_DEVICES
            ;;
        b|B) return ;;
        *)
            echo -e "   ${C_GRAY}Érvénytelen választás.${C_OFF}"
            sleep 1
            ;;
    esac

    echo ""
    read -rp "   Nyomj Entert a főmenühöz..." _
}

# ── Vision teszt menü ─────────────────────────────────────────────────────────
vision_test_menu() {
    # 1. Videó választás
    header
    echo -e "   ${C_BOLD}Vision teszt — videó választás${C_OFF}"
    echo ""

    if [ ! -d "$VIDEOS_DIR" ]; then
        echo -e "   ${C_RED}Nem található a könyvtár: $VIDEOS_DIR${C_OFF}"
        echo ""
        read -rp "   Nyomj Entert a főmenühöz..." _
        return
    fi

    mapfile -t videos < <(find "$VIDEOS_DIR" -maxdepth 1 -type f \
        \( -iname "*.mp4" -o -iname "*.avi" -o -iname "*.mkv" -o -iname "*.mov" \) \
        | sort)

    if [ ${#videos[@]} -eq 0 ]; then
        echo -e "   ${C_RED}Nincs videófájl a $VIDEOS_DIR könyvtárban.${C_OFF}"
        echo ""
        read -rp "   Nyomj Entert a főmenühöz..." _
        return
    fi

    for i in "${!videos[@]}"; do
        printf "     %2d) %s\n" $((i+1)) "$(basename "${videos[$i]}")"
    done
    echo ""
    echo -e "     ${C_CYAN}r) Véletlenszerű (minden futtatás más videó)${C_OFF}"
    echo -e "     ${C_GRAY}b) Vissza${C_OFF}"
    echo ""
    read -rp "   Videó száma (vagy r): " vsel

    [[ "$vsel" =~ ^[bB]$ ]] && return

    local random_mode=false
    local video=""

    if [[ "$vsel" =~ ^[rR]$ ]]; then
        random_mode=true
    elif [[ "$vsel" =~ ^[0-9]+$ ]] && \
         [ "$vsel" -ge 1 ] && [ "$vsel" -le "${#videos[@]}" ]; then
        video="${videos[$((vsel-1))]}"
    else
        echo -e "   ${C_GRAY}Érvénytelen választás.${C_OFF}"
        sleep 1
        return
    fi

    # 2a. Konkrét videó → loop szám
    if [ "$random_mode" = false ]; then
        header
        echo -e "   ${C_BOLD}Vision teszt — ismétlések${C_OFF}"
        echo ""
        echo -e "   Kiválasztott videó: ${C_CYAN}$(basename "$video")${C_OFF}"
        echo ""
        read -rp "   Hányszor játssza le? [1]: " loops
        loops="${loops:-1}"
        if ! [[ "$loops" =~ ^[0-9]+$ ]] || [ "$loops" -lt 1 ]; then
            echo -e "   ${C_GRAY}Érvénytelen szám, 1 lesz.${C_OFF}"
            loops=1
            sleep 1
        fi
    fi

    # 2b. Random → detect count
    if [ "$random_mode" = true ]; then
        header
        echo -e "   ${C_BOLD}Vision teszt — véletlenszerű mód${C_OFF}"
        echo ""
        echo -e "   Videók száma: ${C_CYAN}${#videos[@]} db${C_OFF}"
        echo ""
        read -rp "   Hány detektálást futtasson? [10]: " det_count
        det_count="${det_count:-10}"
        if ! [[ "$det_count" =~ ^[0-9]+$ ]] || [ "$det_count" -lt 1 ]; then
            echo -e "   ${C_GRAY}Érvénytelen szám, 10 lesz.${C_OFF}"
            det_count=10
            sleep 1
        fi
    fi

    # 3. CUDA / CPU
    header
    echo -e "   ${C_BOLD}Vision teszt — feldolgozási mód${C_OFF}"
    echo ""
    if [ "$random_mode" = true ]; then
        echo -e "   Mód      : ${C_CYAN}Véletlenszerű${C_OFF}"
        echo -e "   Detektálás: ${C_CYAN}${det_count}×${C_OFF}"
    else
        echo -e "   Videó : ${C_CYAN}$(basename "$video")${C_OFF}"
        echo -e "   Loops : ${C_CYAN}${loops}×${C_OFF}"
    fi
    echo ""
    echo "     1) GPU — CUDA"
    echo "     2) CPU — csak processzor"
    echo "     b) Vissza"
    echo ""
    read -rp "   Választás: " m

    [[ "$m" =~ ^[bB]$ ]] && return

    local no_cuda_flag=""
    local mode_label=""
    case "$m" in
        1) unset CUDA_VISIBLE_DEVICES;  mode_label="GPU (CUDA)" ;;
        2) export CUDA_VISIBLE_DEVICES=""; no_cuda_flag="--no-cuda"; mode_label="CPU" ;;
        *)
            echo -e "   ${C_GRAY}Érvénytelen választás.${C_OFF}"
            sleep 1
            return
            ;;
    esac

    # 4. Futtatás
    header
    echo -e "   ${C_BOLD}Vision teszt${C_OFF}"
    if [ "$random_mode" = true ]; then
        echo -e "   Mód       : ${C_CYAN}Véletlenszerű${C_OFF}"
        echo -e "   Detektálás: ${C_CYAN}${det_count}×${C_OFF}"
    else
        echo -e "   Videó : ${C_CYAN}$(basename "$video")${C_OFF}"
        echo -e "   Loops : ${C_CYAN}${loops}×${C_OFF}"
    fi
    echo -e "   Feldolg.: ${C_CYAN}${mode_label}${C_OFF}"
    echo ""

    if [ "$random_mode" = true ]; then
        cd "$BOTCODE" && $PY bench_vision.py \
            --video-dir "$VIDEOS_DIR" \
            --random-count "$det_count" \
            $no_cuda_flag
    else
        cd "$BOTCODE" && $PY bench_vision.py \
            --video "$video" \
            --loops "$loops" \
            $no_cuda_flag
    fi

    unset CUDA_VISIBLE_DEVICES

    echo ""
    read -rp "   Nyomj Entert a főmenühöz..." _
}

# ── Főmenü ────────────────────────────────────────────────────────────────────
while true; do
    header
    echo -e "   ${C_BOLD}Indítási mód:${C_OFF}"
    echo ""
    echo "     1) Normál indítás"
    echo "     2) Teszt UI-s indítás          (--test-ui)"
    echo "     3) Teszt UI + dry-run          (--test-ui --dry-run)"
    echo "     4) Vision teszt"
    echo ""
    echo -e "     ${C_GRAY}q) Kilépés${C_OFF}"
    echo ""
    read -rp "   Választás: " choice

    case "$choice" in
        1) launch_menu "Normál indítás"       "main.py" ;;
        2) launch_menu "Teszt UI-s indítás"   "main.py --test-ui" ;;
        3) launch_menu "Teszt UI + dry-run"   "main.py --test-ui --dry-run" ;;
        4) vision_test_menu ;;
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
