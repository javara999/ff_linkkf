import re

from support import SupportFile


def write_file(data, filepath):
    SupportFile.write_file(filepath, data)


def convert_vtt_to_srt(vtt_data):
    lines = []
    counter = 1

    for block in re.split(r"\r?\n\r?\n", vtt_data.strip()):
        block = block.strip()
        if block == "" or block == "WEBVTT":
            continue

        block_lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip() != ""]
        if not block_lines:
            continue

        if block_lines[0].startswith("WEBVTT"):
            block_lines = block_lines[1:]
        if not block_lines:
            continue

        if "-->" not in block_lines[0] and len(block_lines) > 1 and "-->" in block_lines[1]:
            block_lines = block_lines[1:]

        if "-->" not in block_lines[0]:
            continue

        timing = block_lines[0].replace(".", ",")
        payload = block_lines[1:]

        lines.append(str(counter))
        lines.append(timing)
        lines.extend(payload)
        lines.append("")
        counter += 1

    return "\n".join(lines).strip() + "\n"

