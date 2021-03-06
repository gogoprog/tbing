#!/usr/bin/python2

import os
import sys
import time
import traceback
import collections
import subprocess
import re
import pystache
import fnmatch
import glob
import json
import pprint
import codecs
import argparse
import clang.cindex
from clang.cindex import CursorKind, Diagnostic, TranslationUnit, AccessSpecifier

context = lambda: None
pystache_renderer = pystache.Renderer()
bindings_path = os.getcwd()

class ExtractedArgument(object):
    def __init__(self, name, _type, _full_type):
        self._name = name
        self._type = _type
        self._full_type = _full_type
        self._last = False

    def argument_name(self):
        return self._name

    def argument_type(self):
        if 'types' in context.current_output:
            types = context.current_output['types']
            if self._type in types:
                return types[self._type]

        return self._type

    def argument_type_pascal_case(self):
        rtype = self._type
        if 'types' in context.current_output:
            types = context.current_output['types']
            if rtype in types:
                return types[rtype]

        return self._type[:1].upper() + self._type[1:]

    def argument_full_type(self):
        return self._full_type

    def comma(self):
        return ', ' if not self._last else ''

class ExtractedMethod(object):
    def __init__(self, name):
        self._name = name
        self._other_name = name
        self._result_type = None
        self._arguments = []
        self.const_qualifier = ""

    def method_name(self):
        return self._name

    def method_other_name(self):
        return self._other_name

    def method_name_camel_case(self):
        return self._name[:1].lower() + self._name[1:]

    def method_other_name_camel_case(self):
        return self._other_name[:1].lower() + self._other_name[1:]

    def method_return(self):
        return "return " if self._result_type != "void" else ""

    def result_type(self):
        return self._result_type

    def result_full_type(self):
        return self._result_full_type

    def result_type_pascal_case(self):
        rtype = self._result_type
        if 'types' in context.current_output:
            types = context.current_output['types']
            if rtype in types:
                return types[rtype]

        return self._result_type[:1].upper() + self._result_type[1:]

    def arguments(self):
        return self._arguments

    def setup(self):
        l = len(self._arguments)
        if l > 0:
            self._arguments[l - 1]._last = True

    def method_const_qualifier(self):
        return self.const_qualifier

    def is_valid(self):
        if 'excluded-types' in context.current_rule:
            excludes = context.current_rule['excluded-types']
            if self._result_type in excludes:
                return False

            for arg in self._arguments:
                if arg._type in excludes:
                    return False

        return True

class ExtractedClass(object):
    def __init__(self, name):
        self._name = name
        self.base_name = None
        self.base = None
        self.methods = []

    def class_name(self):
        return self._name

    def class_base_name(self):
        return self.base_name if self.base_name != None else "void"

    def class_name_camel_case(self):
        return self._name[:1].lower() + self._name[1:]

    def methods(self):
        return self._methods

    def has_method(self, name):
        mlen = len(self.methods)
        for i in range(0, mlen): 
            if self.methods[i]._other_name == name:
                return True
        
        if self.base != None:
            return self.base.has_method(name)

        return False

    def setup(self):
        mlen = len(self.methods)
        for i in range(0, mlen):
            dup = 0
            valid = False
            while not valid:
                dup += 1
                valid = True

                if self.base != None and self.base.has_method(self.methods[i]._other_name):
                    self.methods[i]._other_name = self.methods[i]._name + str(dup)
                    valid = False
                    continue

                for j in range(0, mlen):
                    if i != j:
                        if self.methods[i]._other_name == self.methods[j]._other_name:
                            self.methods[i]._other_name = self.methods[i]._name + str(dup)
                            valid = False
                            continue

class Extraction(object):
    def __init__(self):
        self._classes = []
        self.headers = []

    def add_class(self, c):
        self._classes.append(c)

    def classes(self):
        return self._classes

def clang_default_include():
    sub = subprocess.Popen(['clang', '-v', '-x', 'c++', '-'],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    _, out = sub.communicate('')
    reg = re.compile('lib/clang.*/include$')
    return next(line.strip() for line in out.split('\n') if reg.search(line))

def start_process(rule):
    headers = []
    real_root = os.path.realpath(rule['root'])
    include_relative = os.path.realpath(rule['include-relative'])
    for subdir, dirs, files in os.walk(real_root):
        for file in files:
            file_name = subdir + os.sep + file
            for file_rule in rule['files']:
                if fnmatch.fnmatch(file_name, file_rule):
                    if 'excluded-files' in rule:
                        must_append = True
                        for excluded_file_rule in rule['excluded-files']:
                            if fnmatch.fnmatch(file_name, excluded_file_rule):
                                must_append = False
                        if must_append:
                            headers.append(os.path.relpath(os.path.realpath(file_name), include_relative))
                    else:
                        headers.append(os.path.relpath(os.path.realpath(file_name), include_relative))

    file_path = "/tmp/gen-bindings.cpp"
    out = open(file_path, "wb")
    for header in headers:
        out.write("#include \"" + header + "\"\n")
    out.write("int main(int argc, char *argv[]) { return EXIT_SUCCESS; }")
    out.close()

    for output in rule['output']:
        output['extraction'].headers = headers

    index = clang.cindex.Index.create()

    compiler_command_line = [
        '-I', clang_default_include(),
        '-I', include_relative
        ]

    for include_dir in rule['include-dirs']:
        compiler_command_line.append("-I")
        compiler_command_line.append(include_dir)

    tu = index.parse(file_path,
                     compiler_command_line,
                     options=TranslationUnit.PARSE_INCOMPLETE
                     | TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)

    for cursor in tu.cursor.get_children():
        process_cursor(cursor)

def process_cursor(cursor, parent_cursor=None):
    context.current_rule = get_rule_from_cursor(cursor)
    if context.current_rule != None:
        if cursor.kind == CursorKind.CLASS_DECL:
            process_class_cursor(cursor)

    for child_cursor in cursor.get_children():
        process_cursor(child_cursor, cursor)

def process_class_cursor(cursor):
    if 'excluded-types' in context.current_rule:
        excludes = context.current_rule['excluded-types']
        if cursor.spelling in excludes:
            return False

    extracted_class = ExtractedClass(cursor.spelling)
    context.class_map[cursor.spelling] = extracted_class

    for child_cursor in cursor.get_children():
        if child_cursor.access_specifier == AccessSpecifier.PUBLIC:
            kind = child_cursor.kind
            if kind == CursorKind.CXX_METHOD and not child_cursor.is_static_method():
                process_method_cursor(child_cursor, extracted_class)
        if child_cursor.kind == CursorKind.CXX_BASE_SPECIFIER:
            definition = child_cursor.get_definition()
            if extracted_class.base_name == None:
                extracted_class.base_name = definition.spelling
                if definition.spelling in context.class_map:
                    extracted_class.base = context.class_map[definition.spelling]

    extracted_class.setup()
    rule = context.current_rule
    for output in rule['output']:
        generate_class(rule, output, extracted_class)

def get_type_name(input_type):
    if input_type.get_pointee().spelling != "":
        decl = input_type.get_pointee().get_declaration().spelling 
        return decl if decl != "" else input_type.spelling 
    elif input_type.get_declaration().spelling != "":
        return input_type.get_declaration().spelling
    else:
        return input_type.spelling

    return None

def process_method_cursor(cursor, extracted_class):
    extracted_method = ExtractedMethod(cursor.spelling)
    extracted_method.cursor = cursor
    extracted_method._result_type = get_type_name(cursor.result_type)
    extracted_method._result_full_type = cursor.result_type.spelling

    extracted_method.const_qualifier = ' const' if cursor.is_const_method() else ''

    for child_cursor in cursor.get_children():
        if child_cursor.kind == CursorKind.PARM_DECL:
            extracted_method._arguments.append(ExtractedArgument(child_cursor.spelling, get_type_name(child_cursor.type), child_cursor.type.spelling))

    extracted_method.setup()
    if extracted_method.is_valid():
        extracted_class.methods.append(extracted_method)

def get_rule_from_cursor(cursor):
    if cursor.location.file:
        file_name = os.path.realpath(cursor.location.file.name)
        for rule in context.rules:
            for file_rule in rule['files']:
                if fnmatch.fnmatch(file_name, file_rule):
                    if 'base' in rule:
                        if has_base(cursor, rule['base']):
                            return rule
                    else:
                        return rule
    return None

def has_base(cursor, base):
    for child_cursor in cursor.get_children():
        if child_cursor.kind == CursorKind.CXX_BASE_SPECIFIER:
            definition = child_cursor.get_definition()
            name = definition.spelling
            if name == base:
                return True
            else:
                if has_base(definition, base):
                    return True
    return False

def begin_generation(rule):
    context.class_map = {}
    for output in rule['output']:
        with codecs.open(bindings_path + output['template'], 'r', "utf-8") as data_file:
            output['parsed-template'] = pystache.parse(data_file.read())
            output['extraction'] = Extraction()

def end_generation(rule):
    for output in rule['output']:
        if output['rule'] == 'single-file':
            context.current_output = output
            path = bindings_path + output['path']
            ensure_file_path(path)
            with open(path, "w") as f:
                f.write(pystache_renderer.render(output['parsed-template'], output['extraction']))

def generate_class(rule, output, extracted_class):
    if output['rule'] == 'file-per-class':
        context.current_output = output
        path = bindings_path + pystache_renderer.render(output['path'], extracted_class)
        ensure_file_path(path)
        with open(path, "w") as f:
            f.write(pystache_renderer.render(output['parsed-template'], extracted_class))
    else:
        output['extraction'].add_class(extracted_class)

def ensure_file_path(filename):
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

def main():
    print("[tbing] Generating bindings...")

    parser = argparse.ArgumentParser()
    parser.add_argument('dir', help='Target directory', default='.', nargs='?')
    args = parser.parse_args()

    global bindings_path
    if args.dir:
        if os.path.isabs(args.dir):
            bindings_path = args.dir + "/"
        else:
            bindings_path = os.getcwd() + "/" + args.dir + "/"

    print(bindings_path)

    global context
    os.chdir(bindings_path)

    with open(bindings_path + "rules.json") as data_file:
        context.rules = json.load(data_file)

    for index, rule in enumerate(context.rules):
        print("[tbing] Processing rule #" + str(index + 1))
        begin_generation(rule)
        start_process(rule)
        end_generation(rule)

    print("[tbing] Done!")
