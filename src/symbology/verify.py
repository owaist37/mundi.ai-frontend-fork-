# Copyright (C) 2025 Bunting Labs, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import subprocess
import tempfile
import os


class StyleValidationError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


def verify_style_json_str(style_json_str):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
        temp_path = temp_file.name
        temp_file.write(style_json_str.encode("utf-8"))
        temp_file.flush()

    try:
        result = subprocess.run(
            ["gl-style-validate", temp_path], capture_output=True, text=True
        )

        if result.returncode != 0:
            raise StyleValidationError(result.stdout)

        return True
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
