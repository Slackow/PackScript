#!/usr/bin/env python3
import argparse
import inspect
import json
import os
import re
import shutil
import zipfile

DATA_EXT = 'dps'
FUNC_EXT = 'fps'

__version__ = '0.1.0'
latest_mc_version = '1.20.4'
namespace_re = re.compile(r'[a-z0-9-_]+')


def ver(base_version, /, start, end, *, pf):
    return {f'{base_version}.{x}': pf for x in range(start, end + 1)}


pack_formats = {
    '1.20.4': 26, '1.20.3': 26, '1.20.2': 18,
    '1.20.1': 15, '1.20': 15, '1.19.4': 12,
    ** ver('1.19', 1, 3, pf=10),
    '1.19': 10,
    '1.18.2': 9,
    '1.18.1': 8, '1.18': 8,
    '1.17.1': 7, '1.17': 7,
    ** ver('1.16', 2, 5, pf=6),
    '1.16.1': 5, '1.16': 5, '1.15.2': 5, '1.15.1': 5, '1.15': 5,
    ** ver('1.14', 1, 4, pf=4),
    '1.14': 4, '1.13.2': 4, '1.13.1': 4, '1.13': 4,
}


def ns(resource: str, /, *, default: str = 'minecraft'):
    return resource if ':' in resource else f'{default}:{resource}'


func_re = re.compile(r'(?<!-)\bfunction\b(?!-)')


def right_most_function(contents):
    # Use finditer to get match objects, which include the start and end positions of each match
    matches = list(func_re.finditer(contents))
    return matches[-1].end() if matches else None


def comp_file(parent: str, filename: str, globals: list[object], namespace='minecraft', verbose=False):
    command_re = re.compile(r'([\t ]*)/(.*)')
    interpolation_re = re.compile(r'\$\{\{(.*?)}}|(?<!^)\$([a-zA-Z_]\w*)')
    create_statement_re = re.compile(r'([\t ]*)create\b[ \t]*([\w/]+)\b[ \t]*([a-z\d:/_.-]*)[ \t]*->(.*)')
    code = []
    concat_line = None
    with open(os.path.join(parent, filename), 'r') as r:
        for line in r:
            line = line.rstrip()
            if concat_line is not None:
                line = f'{concat_line}{line.lstrip()}'
                concat_line = None
            if line.endswith('\\'):
                concat_line = line[:-1]
                continue

            command_match = command_re.match(line)
            if command_match:
                indent, contents = command_match.groups()
                # replace { and } with other sequences, so they don't interfere with f string
                contents = contents.replace('{', '{{').replace('}', '}}')
                # replace interpolation with value \1\2 is a hack lmao
                # It's basically grabbing from either the first or second group, since they're mutually exclusive
                contents = interpolation_re.sub(r'{\1\2}', contents)
                extra_line = None
                if contents.endswith(':'):
                    func_def_start = right_most_function(contents)
                    # print('func: ', line)
                    if func_def_start is None:
                        raise ValueError(f'Command {contents!r} ends with colon but does not contain function')
                    func_def = contents[func_def_start:-1].strip()
                    code.append(f'{indent}__f, __extra = __function_name__(f"{func_def}")')
                    contents = f'{contents[:func_def_start]} {{__f}}{{__extra}}'
                    extra_line = f'{indent}with __function__(__f):'
                code.append(f'{indent}__line__(rf""" {contents} """[1:-1])')
                if extra_line:
                    code.append(extra_line)
            else:
                create_match = create_statement_re.fullmatch(line)
                if create_match:
                    indent, file_type, name, data = create_match.groups()
                    name = ns(name, default=namespace)
                    code.append(f'{indent}__other__("{file_type}")["{name}"]={data}')
                else:
                    code.append(line)
    print(f'{parent}/{filename}')
    pyth = '\n'.join(code)
    if verbose:
        max_len = len(str(len(code)))
        for i, ln in enumerate(code, start=1):
            print(f'{i:>{max_len}}: {ln}')
    exec(pyth, {func.__name__: func for func in globals})


def build_functions(func_stack: list, capturer_stack: list, func_files: dict,
                    other: dict, namespace='minecraft', function_tags=None):

    def __other__(s: str):
        return other.setdefault(s, {})

    def __line__(ln: str):
        if capturer_stack:
            capturer_stack[-1].append(ln)
        else:
            func_files[func_stack[-1]].append(ln)

    func_def_re = re.compile(r'^([a-z\d:/_-]*)[ \t]*(?:\[([a-z\d:/_, -]*)](.*))?$')

    def __function_name__(func_def: str):
        func_def_match = func_def_re.fullmatch(func_def)
        if not func_def_match:
            raise ValueError(f'Invalid function definition: {func_def!r}')
        func_name, tags, extra = func_def_match.groups()
        if func_name == '':
            func_name = f'{namespace}:anon/function'
            if func_name in func_files:
                x = 1
                while f'{func_name}_{x}' in func_files:
                    x += 1
                func_name = f'{func_name}_{x}'
        func_name = ns(func_name, default=namespace)
        if func_name in func_files:
            raise ValueError(f'Duplicate function name: {func_name!r}')
        if tags and function_tags is not None:
            for tag in tags.split(','):
                tag = ns(tag.strip())
                function_tags.setdefault(tag, []).append(func_name)
        func_files[func_name] = []
        return func_name, extra

    class FuncContext:
        def __init__(self, func_name: str):
            self.func_name = func_name

        def __enter__(self):
            func_stack.append(self.func_name)

        def __exit__(self, exc_type, exc_val, exc_tb):
            func_stack.pop()

    def __function__(func_name: str):
        return FuncContext(func_name)

    class Capturer:
        def __enter__(self):
            capturer = []
            capturer_stack.append(capturer)
            return capturer

        def __exit__(self, exc_type, exc_val, exc_tb):
            capturer_stack.pop()

    def capture_lines():
        return Capturer()

    return [__other__, __line__, __function_name__, __function__, capture_lines]


def comp(*, input, output, verbose, sources, **_):
    try:
        namespaces = os.listdir(os.path.join(input, 'data'))

        is_zip = output.endswith('.zip')
        output_folder = output.removesuffix('.zip')
        if namespaces:
            if not input:
                input = '.'
            data = os.path.join(input, 'data')
            if os.path.exists(data) and os.path.exists(os.path.join(input, 'pack.mcmeta')):
                try:
                    shutil.rmtree(os.path.join(output_folder, 'data'))
                except IOError:
                    pass
                shutil.copytree(data, os.path.join(output_folder, 'data'))
                shutil.copy(os.path.join(input, 'pack.mcmeta'),
                            os.path.join(output_folder, 'pack.mcmeta'))
                if os.path.exists(os.path.join(input, 'pack.png')):
                    shutil.copy(os.path.join(input, 'pack.png'),
                                os.path.join(output_folder, 'pack.png'))
            else:
                raise FileNotFoundError('need data folder and pack.mcmeta')

        function_tags: dict[str, list[str]] = {}
        other: dict[str, dict[str, object]] = {}
        for namespace in namespaces:
            try:
                if not sources:
                    shutil.rmtree(os.path.join(output_folder, 'data', namespace, 'sources'))
            except NotADirectoryError:
                pass
            func_files: dict[str, list[str]] = {'': []}
            func_stack: list[str] = ['']
            capturer_stack: list[str] = []

            functions = build_functions(func_stack, capturer_stack, func_files, other, namespace, function_tags)
            working_folder = os.path.join(input, f'data/{namespace}/sources')
            try:
                for filename in os.listdir(working_folder):
                    if filename.endswith(f'.{DATA_EXT}'):
                        comp_file(working_folder, filename, functions,
                                  namespace, verbose=verbose)
            except NotADirectoryError:
                continue
            func_files.pop('')
            # Iterate through generated functions
            for name, content in func_files.items():
                path = os.path.join(output_folder, f'data/{name.replace(":", "/functions/")}.mcfunction')
                if not content:
                    continue
                try:
                    os.makedirs(os.path.dirname(path))
                except FileExistsError:
                    pass
                with open(path, 'w') as w:
                    w.write(f'# Generated by Packscript {__version__}\n' + '\n'.join(content) + '\n')

            # <editor-fold defaultstate="collapsed" desc="Move function tags into 'other' dictionary">

            other.setdefault('tags/functions', {}).update(
                {tag: {'values': func_names} for tag, func_names in function_tags.items()})

            # </editor-fold>

            # Write stuff in other
            for file_type, stuff in other.items():
                for name, content in stuff.items():
                    name = name.replace(':', f'/{file_type}/')
                    if '.' not in name:
                        name += '.json'
                    path = os.path.join(output_folder, f'data/{name}')
                    try:
                        os.makedirs(os.path.abspath(os.path.join(path, '..')))
                    except FileExistsError:
                        pass
                    with open(path, 'w') as w:
                        if isinstance(content, (dict, list)):
                            json.dump(content, w, indent=2)
                        elif isinstance(content, (str, bytes)):
                            w.write(content)
                        else:
                            raise ValueError(f'Error: invalid content: {content}')
            if is_zip:
                def zipdir(path1, ziph):
                    # ziph is zipfile handle
                    for root, dirs, files1 in os.walk(path1):
                        for file in files1:
                            base = str(os.path.join(root, file))
                            rel = os.path.dirname(path1)
                            ziph.write(os.path.join(root, file), os.path.relpath(base, rel))

                zipf = zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED)
                zipdir(os.path.join(output_folder, 'data'), zipf)
                zipf.write(os.path.join(output_folder, 'pack.mcmeta'), 'pack.mcmeta')
                zipf.close()
                shutil.rmtree(output_folder)
    except FileNotFoundError:
        pass
    func_files = {}
    for f in os.listdir(input):
        if f.endswith(f'.{FUNC_EXT}'):
            func_stack = [f]
            func_files[f] = []

            functions = build_functions(func_stack, [], func_files, {})

            comp_file(input, f, functions, verbose=verbose)
    for f, content in func_files.items():
        path = os.path.join(output, f'{f.removesuffix(f".{FUNC_EXT}")}.mcfunction')
        with open(path, 'w') as w:
            w.write('\n'.join(content) + '\n')


def gen_template(*, name: str, description: str, pack_format: int, output: str, namespace: str, **_):
    if not all((name, description, pack_format, output, namespace)):
        print('Leave a field empty to have it default')
    namespace = namespace or input('Namespace (main): ') or 'main'
    namespace = re.sub(r'\W', '-', namespace.lower().replace(' ', '_'))
    if not namespace_re.fullmatch(namespace):
        raise ValueError(f'namespace must match regex: /{namespace_re.pattern}/ ({namespace} does not match)')
    name = name or input('Datapack Name (Datapack): ') or 'datapack'
    x = latest_mc_version
    pack_format = pack_format or \
        pack_formats.get(x := (input(f'Pack Format/Minecraft Version ({x}): ') or x)) or \
        int(x or next(iter(pack_formats.values())))
    description = description or input(f'Description (Datapack {name!r} for version {x}): ') or \
        f'Datapack {name!r} for version {x}'
    output = output or input(f'Output Directory ({name.replace(" ", "_")}): ') or name.replace(' ', '_')
    sources = os.path.join(output, f'data/{namespace}/sources')
    try:
        os.makedirs(sources)
    except FileExistsError:
        pass
    with open(os.path.join(os.path.join(sources, f'main.{DATA_EXT}')), 'w') as w:
        w.write(inspect.cleandoc(f'''
                /function tick [tick]:
                    /seed
                /function load [load]:
                    /tellraw @a "Loaded {name}"
'''))

    with open(os.path.join(output, 'pack.mcmeta'), 'w') as w:
        json.dump({
            'pack': {
                'pack_format': pack_format,
                'description': description
            }
        }, w, indent=4)


def main():
    parser = argparse.ArgumentParser(
        description='This is a datapack compiler for Minecraft\n'
                    'Source: https://github.com/Slackow/packscript',
        formatter_class=argparse.RawTextHelpFormatter,
        usage='packscript [-V | --version] [-h | --help] <command> [<args>]')
    parser.add_argument('-V', '--version', help='Print out the version', default=False, action='store_true')
    subparsers = parser.add_subparsers(dest='command', title='Commands', metavar='')

    # "compile" command
    parser_compile = subparsers.add_parser('compile', aliases=['comp', 'c'],
                                           help='Compile the datapack. Accepts arguments.\n'
                                                '"packscript comp --help" for more info',
                                           description='Compile the datapack\n\n'
                                                       'Use this command to compile your datapack into a format that '
                                                       'Minecraft can read.',
                                           formatter_class=argparse.RawTextHelpFormatter)
    parser_compile.add_argument('-o', '--output', type=str, help='Output directory', default='output')
    parser_compile.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_compile.add_argument('-v', '--verbose', help='Print generated python code.', default=False,
                                action='store_true')
    parser_compile.add_argument('-S', '--sources', help='Include source files in output.', default=False,
                                action='store_true')

    # "generate" command
    parser_generate = subparsers.add_parser('generate', aliases=['gen', 'g'],
                                            help='Generate datapack template (interactively). Accepts arguments.\n'
                                                 '"packscript gen --help" for more info',
                                            description='Generate a new datapack template\n\n'
                                                        'Use this command to create a new datapack template, setting '
                                                        'up a basic structure for your project. '
                                                        'Information can be provided in args or interactively',
                                            formatter_class=argparse.RawTextHelpFormatter)
    parser_generate.add_argument('-o', '--output', type=str, help='Output directory', default='')
    parser_generate.add_argument('-N', '--name', type=str, help='Name of the datapack', default='')
    parser_generate.add_argument('-n', '--namespace', type=str, help='Custom namespace name', default='')
    parser_generate.add_argument('-d', '--description', type=str, help='The description of the datapack', default='')
    parser_generate.add_argument('-f', '--pack-format', type=int,
                                 help='Pack format (keeps track of compatible versions)', default=0)
    args = parser.parse_args()

    args_dict = {key.replace('-', '_'): val for key, val in vars(args).items()}
    if args.version:
        print(f'Packscript {__version__}')
    elif args.command is None:
        parser.print_help()
    elif args.command.startswith('c'):
        comp(**args_dict)
    else:
        gen_template(**args_dict)


if __name__ == '__main__':
    main()
