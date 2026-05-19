#!/usr/bin/env python3
# -*- coding=utf-8 -*-

#
# UISEE Corp Copyright
#

'''
Json Checker

Run as:
    python3 [-h] [-r] [--base BASE_JSON] [--limit DIFF_LIMIT] [--version] [inputs ...]
    positional arguments:
        inputs          json files or a directory (default ./)

    optional arguments:
        -h, --help  show this help message and exit
        -r          check recursively
        --base      baseline json file path
        --limit     limit diff entries shown per file (0=all)
        --version   show program's version number and exit
Output as:
    Json Checker:
    File: "uos_camera.json", line 12 - json file name, first error line number
    Defined lines(default 5) of content around error line number
'''


import os
import sys
import json
import argparse
import zlib

NUMBER_CONTENTS_SHOW = 5
COMMENT_SINGLELINE = "//"
COMMENT_MULTILINE_START = "/*"
COMMENT_MULTILINE_END = "*/"
QUOTATION = '"'
SPECIAL_CHECK_FILE = "uos_common.json"
CONFIG_SCHEMA_FILE = "./etc/config_schema.bin"
SCHEMA_SPLIT = ":"

RESET = '\033[0m'
COLOR_TITLE = '\033[1;36m'
COLOR_CHANGED = '\033[1;33m'
COLOR_ADDED = '\033[1;32m'
COLOR_REMOVED = '\033[1;31m'
COLOR_PATH = '\033[1;35m'

class Json_Checker:

    def __init__(self, json_file, key_schema=None):
        self.file = json_file
        self.original_error = None
        self.error_lines = None
        self.check_common_json = (os.path.basename(self.file) == \
                SPECIAL_CHECK_FILE)
        self.success = False
        self.key_list = []
        self.key_schema = key_schema
        self.error_keys = None

    def display_error(self):
        if self.success != True:
            if self.original_error is not None:
                print (self.original_error)
            if self.error_lines is not None:
                print (self.error_lines)
            if self.error_keys is not None:
                print ("\nInvalid key detected:")
                for item in self.error_keys:
                    print (item)
        return self.success

    # Remove all comments
    def clear_comments(self, json_lines):
        lines = json_lines
        current_line = 0;
        multi_comment_start = False
        for line in lines:

            current_line += 1

            if len(line) == 0:
                self.update_line(lines, current_line, "")
                continue

            # Remove comments start with '//'
            line = self.remove_single_comments(line)
            if len(line) == 0:
                self.update_line(lines, current_line, "")
                continue

            pos_multi_comment_start = line.find(COMMENT_MULTILINE_START)
            pos_multi_comment_end = line.find(COMMENT_MULTILINE_END)
            if pos_multi_comment_start != -1 and pos_multi_comment_end != -1:
                if multi_comment_start is True:
                    print ("Has nesting multi comment.")
                else:
                    tmp_pos_multi_comment_start = line.find(COMMENT_MULTILINE_START, pos_multi_comment_start+len(COMMENT_MULTILINE_START))
                    if tmp_pos_multi_comment_start != -1:
                        tmp_pos_multi_comment_end = line.find(COMMENT_MULTILINE_END, tmp_pos_multi_comment_start)
                        if tmp_pos_multi_comment_end != -1:
                            print ("Has nesting multi comment.")

                line = line.replace(line[pos_multi_comment_start: \
                        pos_multi_comment_end + \
                        len(COMMENT_MULTILINE_END)], "")
            elif pos_multi_comment_start != -1:
                line = line[0:pos_multi_comment_start]
                if multi_comment_start is True:
                    print ("Has nesting multi comment.")
                else:
                    multi_comment_start = True
            elif pos_multi_comment_end != -1:
                line = line[pos_multi_comment_end + \
                        len(COMMENT_MULTILINE_END):]
                multi_comment_start = False
            elif multi_comment_start == True:
                self.update_line(lines, current_line, "")
                continue
            if len(line) == 0:
                self.update_line(lines, current_line, "")
                continue

            self.update_line(lines, current_line, line)

        # Generate json string and send to python.json
        json_string = ""
        for line in lines:
            json_string += line
        # print(json_string)

        return json_string

    def remove_single_comments(self, line):
        slash_pos = -1
        pos_base = 0
        while True:
            slash_pos = line.find(COMMENT_SINGLELINE, pos_base)
            if slash_pos == -1:
                return line
            pos_base =  slash_pos + len(COMMENT_SINGLELINE)
            if line.count(QUOTATION, 0, pos_base) % 2 == 0:
                return line[0:slash_pos]

    def read_file(self):
        try:
            jsonSrc = open(self.file, 'r')
        except:
            print ('Exception: cannot open ' + self.file)
            return False, ""

        try:
            lines = jsonSrc.read().splitlines()
        except:
            print ('Exception: cannot read ' + self.file)
            return False, ""

        return True, lines

    def check_redefinition_hook(self, list):
        count={}
        for key,val in list:
            self.key_list.append(key)
            if key not in count.keys():
                count[key] = val
            else:
                raise UserWarning("%s is redefined." %(key))
        return count

    def do_process(self):

        res, lines = self.read_file()
        if False == res:
            self.success = False
            return None

        # Generate json string and send to python.json
        json_string = self.clear_comments(lines)
        # print(json_string)

        try:
            parsed = json.loads(json_string, object_pairs_hook=self.check_redefinition_hook)
        except ValueError as e:
            self.original_error = str(e)
            for part in self.original_error.split():
                if part.isdigit():
                    current_line = int(part) - 1
                    break
            start = max(current_line - (NUMBER_CONTENTS_SHOW / 2), 0)
            end = min(current_line + (NUMBER_CONTENTS_SHOW / 2), len(lines) - 1)
            self.error_lines = ""
            while start < end + 1:
                self.error_lines += str(start + 1) + lines[start]
                start += 1

            self.success = False
            return None

        # Check invalid key for common.json
        self.key_list = list(set(self.key_list))
        if self.check_common_json == True \
                and self.check_invalid_key() == False:
            self.success = False
            return None

        self.success = True
        return parsed

    def update_line(self, lines, line_num, new_line):
        lines[line_num - 1] = new_line + '\n'

    def get_all_keys(self):
        return self.key_list

    def check_invalid_key(self):
        if self.key_schema is None:
            return True
        self.error_keys = [item for item in self.key_list if item not in self.key_schema]
        return (0 == len(self.error_keys))

def dirlist(path, all_file, recursive):
    file_list = os.listdir(path)

    for file_name in file_list:
        file_path = os.path.join(path, file_name)
        if os.path.isdir(file_path) and recursive == True:
            dirlist(file_path, all_file, recursive)
        else:
            if file_path.endswith('.json'):
                all_file.append(file_path)

    return all_file

def _to_unicode(s):
    try:
        if isinstance(s, bytes):
            return s.decode('utf-8', 'replace')
    except NameError:
        pass
    try:
        if isinstance(s, unicode):
            return s
    except NameError:
        pass
    return str(s)

def _value_repr(v):
    try:
        return _to_unicode(json.dumps(v, ensure_ascii=False, sort_keys=True))
    except Exception:
        return _to_unicode(v)

def _path_repr(path_items):
    out = ""
    for item in path_items:
        if isinstance(item, int):
            out += "[%d]" % item
        else:
            out += "[%s]" % _to_unicode(item)
    return out if out else "[]"

def _diff_values(base_val, other_val, path_items, out_changes):
    if isinstance(base_val, dict) and isinstance(other_val, dict):
        all_keys = set(base_val.keys()) | set(other_val.keys())
        for k in sorted(all_keys, key=lambda x: _to_unicode(x)):
            in_base = k in base_val
            in_other = k in other_val
            new_path = path_items + [k]
            if (not in_base) and in_other:
                out_changes.append(("added", new_path, None, other_val.get(k)))
            elif in_base and (not in_other):
                out_changes.append(("removed", new_path, base_val.get(k), None))
            else:
                _diff_values(base_val.get(k), other_val.get(k), new_path, out_changes)
        return

    if isinstance(base_val, list) and isinstance(other_val, list):
        max_len = max(len(base_val), len(other_val))
        for i in range(max_len):
            in_base = i < len(base_val)
            in_other = i < len(other_val)
            new_path = path_items + [i]
            if (not in_base) and in_other:
                out_changes.append(("added", new_path, None, other_val[i]))
            elif in_base and (not in_other):
                out_changes.append(("removed", new_path, base_val[i], None))
            else:
                _diff_values(base_val[i], other_val[i], new_path, out_changes)
        return

    if base_val != other_val:
        out_changes.append(("changed", path_items, base_val, other_val))

def _get_vehicle_name(parsed, fallback):
    try:
        name = parsed.get("_MOD_uos_config", {}).get("real_vehicle_name")
        if name is None:
            return fallback
        return _to_unicode(name)
    except Exception:
        return fallback

def _resolve_inputs(inputs, recursive):
    files = []
    for item in inputs:
        if item is None:
            continue
        p = os.path.abspath(item)
        if os.path.isdir(p):
            files.extend(dirlist(p, [], recursive))
        elif os.path.isfile(p) and p.endswith(".json"):
            files.append(p)
    files = sorted(list(set(files)))
    return files

def compare_json_files(base_parsed, other_parsed, base_label, other_label, limit=0):
    changes = []
    _diff_values(base_parsed, other_parsed, [], changes)
    counts = {"changed": 0, "added": 0, "removed": 0}
    for kind, _, _, _ in changes:
        counts[kind] += 1

    print(COLOR_TITLE + "============================================================" + RESET)
    print(COLOR_TITLE + "BASE : " + RESET + _to_unicode(base_label))
    print(COLOR_TITLE + "OTHER: " + RESET + _to_unicode(other_label))
    print(COLOR_TITLE + "SUMMARY: " + RESET + "changed=%d, added=%d, removed=%d, total=%d" % (
        counts["changed"], counts["added"], counts["removed"], len(changes)
    ))

    if len(changes) == 0:
        print(COLOR_ADDED + "No differences" + RESET)
        return counts, changes

    shown = changes if (limit is None or int(limit) <= 0) else changes[:int(limit)]
    for kind, path_items, base_val, other_val in shown:
        if kind == "changed":
            c = COLOR_CHANGED
            tag = "~"
        elif kind == "added":
            c = COLOR_ADDED
            tag = "+"
        else:
            c = COLOR_REMOVED
            tag = "-"

        print(c + ("%s " % tag) + COLOR_PATH + _path_repr(path_items) + RESET)
        if kind in ("changed", "removed"):
            print("  %s: %s" % (_to_unicode(base_label), _value_repr(base_val)))
        if kind in ("changed", "added"):
            print("  %s: %s" % (_to_unicode(other_label), _value_repr(other_val)))

    if len(shown) != len(changes):
        print(COLOR_TITLE + "...... truncated, showing %d/%d diffs (use --limit 0 to show all)" % (len(shown), len(changes)) + RESET)

    return counts, changes

##################################### Main #####################################
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", action="store_true", dest="check_recursive", \
            help="check recursively")
    parser.add_argument("--base", dest="base_json", default=None, \
            help="baseline json file path")
    parser.add_argument("--limit", dest="diff_limit", type=int, default=0, \
            help="limit diff entries shown per file (0=all)")
    parser.add_argument("inputs", nargs="*", default=[os.getcwd()], \
            help="json files or a directory (default ./)")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")
    uos_opts=parser.parse_args()

    print ('Json Checker:\n')

    parse_recursive = uos_opts.check_recursive
    inputs = uos_opts.inputs
    all_files = _resolve_inputs(inputs, parse_recursive)
    if uos_opts.base_json is not None:
        base_path = os.path.abspath(uos_opts.base_json)
        if os.path.isfile(base_path) and base_path.endswith(".json") and base_path not in all_files:
            all_files.append(base_path)
        all_files = sorted(list(set(all_files)))
    if len(all_files) < 2:
        print('Need at least 2 json files. Inputs: %s' % _to_unicode(inputs))
        sys.exit(2)

    print('Start to parse .json files (recursive=%s)\n' % ('true' if parse_recursive else 'false'))

    key_schema = None
    if os.path.exists(CONFIG_SCHEMA_FILE):
        with open(CONFIG_SCHEMA_FILE, 'rb') as myfile:
            schema_data = zlib.decompress(myfile.read())
            try:
                schema_data = schema_data.decode('utf-8', 'replace')
            except Exception:
                pass
            key_schema = schema_data.split(SCHEMA_SPLIT)

    all_pass = True
    parsed_map = {}

    for file_name in all_files:

        print ('checking:', file_name)
        json_checker=Json_Checker(file_name, key_schema)
        parsed=json_checker.do_process()
        parsed_map[file_name] = parsed
        if json_checker.display_error() == False:
            all_pass = False

    ret = 0 if all_pass else 1
    print ('\nJson Checker Done[', ret, ']\n')

    if uos_opts.base_json is not None:
        base_file = os.path.abspath(uos_opts.base_json)
    else:
        base_file = all_files[0]

    base_parsed = parsed_map.get(base_file)
    if base_parsed is None:
        print('Baseline json failed to parse: %s' % _to_unicode(base_file))
        sys.exit(2)

    base_label = _get_vehicle_name(base_parsed, os.path.basename(base_file))
    any_diff = False
    for other_file in all_files:
        if other_file == base_file:
            continue
        other_parsed = parsed_map.get(other_file)
        if other_parsed is None:
            continue
        other_label = _get_vehicle_name(other_parsed, os.path.basename(other_file))
        counts, _ = compare_json_files(base_parsed, other_parsed, base_label, other_label, limit=uos_opts.diff_limit)
        if (counts["changed"] + counts["added"] + counts["removed"]) > 0:
            any_diff = True

    if any_diff:
        print(COLOR_TITLE + "\nDiff Done: differences detected" + RESET)
    else:
        print(COLOR_TITLE + "\nDiff Done: no differences" + RESET)

    sys.exit(ret)



if __name__ == "__main__":
    main()
