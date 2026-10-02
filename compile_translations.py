import ast
import struct
from pathlib import Path


PROJECT_DIRECTORY = Path(__file__).resolve().parent
SOURCE_DIRECTORY = PROJECT_DIRECTORY / "lang"
OUTPUT_DIRECTORY = SOURCE_DIRECTORY / "bin"


def parse_po(path):
    messages = {}
    message_id = []
    message_string = []
    active_section = None
    fuzzy = False

    def store_message():
        if message_id and not fuzzy:
            messages["".join(message_id)] = "".join(
                message_string
            )

    for raw_line in path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if line.startswith("#, "):
            fuzzy = "fuzzy" in line

        elif line.startswith("msgid "):
            store_message()
            message_id = [
                ast.literal_eval(line[6:])
            ]
            message_string = []
            active_section = "msgid"
            fuzzy = False

        elif line.startswith("msgstr "):
            message_string = [
                ast.literal_eval(line[7:])
            ]
            active_section = "msgstr"

        elif line.startswith('"'):
            value = ast.literal_eval(line)

            if active_section == "msgid":
                message_id.append(value)

            elif active_section == "msgstr":
                message_string.append(value)

    store_message()

    return messages


def compile_mo(messages):
    encoded_messages = [
        (
            message_id.encode("utf-8"),
            message_string.encode("utf-8")
        )
        for message_id, message_string
        in sorted(messages.items())
    ]

    message_count = len(encoded_messages)
    original_table_offset = 7 * 4
    translation_table_offset = (
        original_table_offset
        + message_count * 8
    )
    original_data_offset = (
        translation_table_offset
        + message_count * 8
    )

    original_data = b""
    translation_data = b""
    original_table = []
    translation_table = []

    for original, translation in encoded_messages:
        original_table.append(
            (
                len(original),
                original_data_offset + len(original_data)
            )
        )
        original_data += original + b"\0"

    translation_data_offset = (
        original_data_offset
        + len(original_data)
    )

    for original, translation in encoded_messages:
        translation_table.append(
            (
                len(translation),
                translation_data_offset + len(translation_data)
            )
        )
        translation_data += translation + b"\0"

    output = struct.pack(
        "<7I",
        0x950412DE,
        0,
        message_count,
        original_table_offset,
        translation_table_offset,
        0,
        0
    )

    for length, offset in original_table:
        output += struct.pack(
            "<2I",
            length,
            offset
        )

    for length, offset in translation_table:
        output += struct.pack(
            "<2I",
            length,
            offset
        )

    return output + original_data + translation_data


def main():
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True
    )

    for source_path in sorted(
        SOURCE_DIRECTORY.glob("*.po")
    ):
        output_path = (
            OUTPUT_DIRECTORY
            / f"{source_path.stem}.mo"
        )

        output_path.write_bytes(
            compile_mo(
                parse_po(source_path)
            )
        )

        print(
            f"Compiled {source_path.name} -> {output_path.name}"
        )


if __name__ == "__main__":
    main()
