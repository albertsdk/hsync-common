#!/usr/bin/env bash
#
# Generate PNG images from Mermaid diagrams in documentation
#
# Requirements:
#   - Docker
#
# Usage:
#   ./generate-diagrams.sh
#
# Author: Alberto Basso
# =============================================================================

set -euo pipefail

# Colors
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[0;33m'
    BLUE=$'\033[0;34m'
    NC=$'\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="${SCRIPT_DIR}/images"
DOCKER_IMAGE="minlag/mermaid-cli"

# Check for Docker
if ! command -v docker &> /dev/null; then
    printf '%s\n' "${RED}Error: Docker not found${NC}"
    printf '%s\n' "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# Create images directory
mkdir -p "${IMAGES_DIR}"

# Mermaid config for better rendering
CONFIG_FILE="${SCRIPT_DIR}/mermaid-config.json"
cat > "${CONFIG_FILE}" << 'EOF'
{
  "theme": "default",
  "themeVariables": {
    "fontSize": "14px",
    "fontFamily": "arial,sans-serif"
  },
  "flowchart": {
    "useMaxWidth": false,
    "htmlLabels": true
  },
  "sequence": {
    "useMaxWidth": false
  }
}
EOF

# Render diagram using Docker
render_diagram() {
    local input_file="$1"
    local output_file="$2"
    local input_name
    local output_name
    input_name=$(basename "${input_file}")
    output_name=$(basename "${output_file}")

    docker run --rm \
        -u "$(id -u):$(id -g)" \
        -v "${SCRIPT_DIR}:/data" \
        "${DOCKER_IMAGE}" \
        -i "/data/${input_name}" \
        -o "/data/images/${output_name}" \
        -c "/data/mermaid-config.json" \
        -b transparent \
        -s 2 \
        2>/dev/null
}

# Extract and render Mermaid diagrams from markdown files
extract_and_render() {
    local md_file="$1"
    local base_name
    base_name=$(basename "${md_file}" .md)

    printf '%s\n' "${BLUE}Processing: ${md_file}${NC}"

    local diagram_num=0
    local in_mermaid=0
    local mermaid_content=""

    while IFS= read -r line; do
        if [[ "${line}" == '```mermaid' ]]; then
            in_mermaid=1
            mermaid_content=""
        elif [[ "${line}" == '```' ]] && [[ ${in_mermaid} -eq 1 ]]; then
            in_mermaid=0
            diagram_num=$((diagram_num + 1))

            local temp_file="${SCRIPT_DIR}/${base_name}-${diagram_num}.mmd"
            local output_file="${IMAGES_DIR}/${base_name}-${diagram_num}.png"

            printf '%s\n' "${mermaid_content}" > "${temp_file}"

            if render_diagram "${temp_file}" "${output_file}"; then
                printf '%s\n' "  ${GREEN}✓${NC} Generated: ${base_name}-${diagram_num}.png"
            else
                printf '%s\n' "  ${YELLOW}⚠${NC} Failed: ${base_name}-${diagram_num}.png"
            fi

            rm -f "${temp_file}"
        elif [[ ${in_mermaid} -eq 1 ]]; then
            mermaid_content+="${line}"$'\n'
        fi
    done < "${md_file}"

    if [[ ${diagram_num} -eq 0 ]]; then
        printf '%s\n' "  ${YELLOW}No diagrams found${NC}"
    fi
}

# Pull Docker image if not present
printf '%s\n' "${BLUE}Checking Docker image...${NC}"
if ! docker image inspect "${DOCKER_IMAGE}" &>/dev/null; then
    printf '%s\n' "${YELLOW}Pulling ${DOCKER_IMAGE}...${NC}"
    docker pull "${DOCKER_IMAGE}"
fi

# Process all markdown files in docs directory
printf '%s\n' ""
printf '%s\n' "${GREEN}=== Generating Mermaid Diagrams ===${NC}"
printf '%s\n' ""

for md_file in "${SCRIPT_DIR}"/*.md; do
    if [[ -f "${md_file}" ]]; then
        extract_and_render "${md_file}"
    fi
done

# Process README.md in parent directory
README_FILE="${SCRIPT_DIR}/../README.md"
if [[ -f "${README_FILE}" ]]; then
    extract_and_render "${README_FILE}"
fi

# Cleanup
rm -f "${CONFIG_FILE}"

printf '%s\n' ""
printf '%s\n' "${GREEN}Done! Images saved to: ${IMAGES_DIR}${NC}"
