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

version = '0.1.0'
latest_version = '1.20.4'
namespace_re = re.compile(r'[a-z0-9-_]+')


def ver(base_version, start, end, *, pf):
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


def ns(resource: str, /, *, default: str = "minecraft"):
    return resource if ':' in resource else f"{default}:{resource}"


def comp_file(files: dict[str, object], parent: str, filename: str, globals: list[object],
              function_tags: dict, namespace='minecraft', verbose=False) -> None:
    command_line = re.compile(r'([\t ]*)/(.*)')
    interpolation = re.compile(r'\$\{\{(.*?)}}')
    create_statement = re.compile(r'([\t ]*)create\b[ \t]*([\w/]+)\b[ \t]*([a-z\d:/_-]*)[ \t]*->(.*)')
    code = []
    concat_line = None
    with open(os.path.join(parent, filename), 'r') as r:
        for line in r:
            line = line.rstrip('\n')

            if concat_line is not None:
                line = f'{concat_line}{line.lstrip()}'
                concat_line = None
            if line.endswith('\\'):
                concat_line = line[:-1]
                continue

            found = command_line.match(line)
            if found:
                indent, contents = found.group(1), found.group(2)
                # replace { and } with other sequences, so they don't interfere with f string
                contents = contents.replace('{', '{{').replace('}', '}}')
                # replace interpolation with value
                contents = interpolation.sub(r"{\1}", contents)
                extra_line = None
                if contents.endswith(':'):
                    func_re = re.compile(
                        r'function\b[ \t]*'
                        r'([a-z\d:/_-]*)\b[\t ]*(?:\['
                        r'([a-z\d:/_, -]*)])?[\t ]*:$')
                    match_res = func_re.search(contents)
                    if not func_re:
                        raise ValueError(f"Command ends with colon but does not contain function: "
                                         f"{command_line}")
                    func_name, tags = match_res.group(1), match_res.group(2)
                    if func_name == '':
                        func_name = f'{namespace}:anon/function'
                    func_name = ns(func_name, default=namespace)
                    if func_name in files:
                        x = 1
                        while f'{func_name}_{x}' in files:
                            x += 1
                        func_name = f'{func_name}_{x}'
                    files[func_name] = []
                    if tags:
                        for tag in tags.split(','):
                            tag = ns(tag.strip())
                            function_tags.setdefault(tag, []).append(func_name)
                    extra_line = f'{indent}while __function__("{func_name}"):'
                    contents = f'{contents[:match_res.span()[0]]}function {func_name}'
                code.append(f'{indent}__line__(rf""" {contents} """[1:-1])')
                if extra_line:
                    code.append(extra_line)
            else:
                create = create_statement.fullmatch(line)
                if create:
                    indent, file_type, name, data = \
                        (create.group(i) for i in range(1, 5))
                    name = ns(name, default=namespace)
                    code.append(f'{indent}__other__("{file_type}")["{name}"] ={data}')
                else:
                    code.append(line)
    print(f'{parent}/{filename}')
    pyth = '\n'.join(code)
    if verbose:
        print(pyth)
    exec(pyth, {func.__name__: func for func in globals}, {})


def build_functions(fun_stack: list, capturer_stack: list, files: dict, other: dict):
    def __other__(s: str):
        return other.setdefault(s, {})

    def __line__(ln: str):
        if capturer_stack:
            capturer_stack[-1].append(ln)
        else:
            files[fun_stack[-1]].append(ln)

    def __function__(fun_name: str):
        if fun_stack[-1] == fun_name:
            fun_stack.pop()
            return False
        else:
            fun_stack.append(fun_name)
            return True

    class Capturer:
        def __enter__(self):
            capturer = []
            capturer_stack.append(capturer)
            return capturer

        def __exit__(self, exc_type, exc_val, exc_tb):
            capturer_stack.pop()

    def capture_lines():
        return Capturer()

    return [__other__, __line__, __function__, capture_lines]


def comp(*, input, output, verbose, **_):
    try:
        for namespace in os.listdir(os.path.join(input, 'data')):
            files: dict[str, list[str]] = {'': []}
            function_tags: dict[str, list[str]] = {}
            other: dict[str, dict[str, object]] = {}
            fun_stack = ['']
            capturer_stack = []

            functions = build_functions(fun_stack, capturer_stack, files, other)

            if not input:
                input = '.'
            data = os.path.join(input, 'data')
            if os.path.exists(data) and os.path.exists(os.path.join(input, 'pack.mcmeta')):
                is_zip = output.endswith('.zip')
                output_folder = output.removesuffix('.zip')
                shutil.rmtree(output_folder)
                shutil.copytree(data, os.path.join(output_folder, 'data'))
                shutil.copy(os.path.join(input, 'pack.mcmeta'),
                            os.path.join(output_folder, 'pack.mcmeta'))
                if os.path.exists(os.path.join(input, 'pack.png')):
                    shutil.copy(os.path.join(input, 'pack.png'),
                                os.path.join(output_folder, 'pack.png'))

            else:
                raise FileNotFoundError('need data folder and pack.mcmeta')
            working_folder = os.path.join(input, f'data/{namespace}/sources')
            try:
                for filename in os.listdir(working_folder):
                    if filename.endswith(f'.{DATA_EXT}'):
                        comp_file(files, working_folder, filename, functions,
                                  function_tags, namespace, verbose=verbose)
            except NotADirectoryError:
                continue
            files.pop('')
            # Iterate through generated functions
            for name, content in files.items():
                path = os.path.join(output_folder, f'data/{name.replace(":", "/functions/")}.mcfunction')
                try:
                    os.makedirs(os.path.dirname(path))
                except FileExistsError:
                    pass
                with open(path, 'w') as w:
                    w.write(f'# Generated by Packscript {version}\n' + '\n'.join(content) + '\n')

            # <editor-fold defaultstate="collapsed" desc="Move function tags into 'other' dictionary">

            other.setdefault('tags/functions', {}).update(
                {tag: {'values': func_names} for tag, func_names in function_tags.items()})

            # </editor-fold>

            # Write stuff in other
            for file_type, stuff in other.items():
                for name, content in stuff.items():
                    path = os.path.join(output_folder, f'data/{name.replace(":", f"/{file_type}/")}.json')
                    try:
                        os.makedirs(os.path.abspath(os.path.join(path, '..')))
                    except FileExistsError:
                        pass
                    with open(path, 'w') as w:
                        if isinstance(content, dict) or isinstance(content, list):
                            json.dump(content, w, indent=2)
                        elif isinstance(content, str):
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
    files = {}
    for f in os.listdir(input):
        if f.endswith(f'.{FUNC_EXT}'):
            fun_stack = [f]
            files[f] = []

            functions = build_functions(fun_stack, [], files, {})

            comp_file(files, input, f, functions, {})
    for f, content in files.items():
        print('lol:', f)
        path = os.path.join(output, f'{f.removesuffix(f".{FUNC_EXT}")}.mcfunction')
        with open(path, 'w') as w:
            w.write('\n'.join(content) + '\n')


def gen_template(*, name: str, description: str, pack_format: int, output: str, namespace: str, **_):
    if not all((name, description, pack_format, output, namespace)):
        print("Leave a field empty to have it default")
    namespace = namespace or input('Namespace (main): ') or 'main'
    namespace = re.sub(r'\W', '-', namespace.lower().replace(' ', '_'))
    if not namespace_re.fullmatch(namespace):
        raise ValueError(f'namespace must match regex: /{namespace_re.pattern}/ ({namespace} does not match)')
    name = name or input('Datapack Name (Datapack): ') or 'datapack'
    x = latest_version
    pack_format = pack_format or \
        pack_formats.get(x := input(f'Pack Format/Minecraft Version ({x}):')) or \
        int(x or next(iter(pack_formats.values())))
    description = description or input(f"Description (Datapack '{name}' for version {x}): ") or \
        f"Datapack '{name}' for version {x}"
    sources = os.path.join(output, f'data/{namespace}/sources')
    try:
        os.makedirs(sources)
    except FileExistsError:
        pass
    with open(os.path.join(os.path.join(sources, f'main.{DATA_EXT}')), 'w') as w:
        w.write(inspect.cleandoc(f"""
                /function tick [tick]:
                    pass
                /function load [load]:
                    /say loaded {name}"""))

    with open(os.path.join(output, 'pack.mcmeta'), 'w') as w:
        json.dump({
            "pack": {
                "pack_format": pack_format,
                "description": description
            }
        }, w, indent=4)


def main():
    # Argument parsing
    parser = argparse.ArgumentParser(description='This is a datapack compiler for Minecraft')
    subparsers = parser.add_subparsers(dest="command")

    # create the parser for the "compile" command
    parser_compile = subparsers.add_parser('compile', aliases=['comp', 'c'], help='Compile the datapack')
    parser_compile.add_argument('-o', '--output', type=str, help='Output directory', default='output')
    parser_compile.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_compile.add_argument('-v', '--verbose', help='Print Generated Python Code', default=False,
                                action='store_true')

    # create the parser for the "generate" command
    parser_generate = subparsers.add_parser('generate', aliases=['gen', 'g'], help='Generate datapack template')
    parser_generate.add_argument('-o', '--output', type=str, help='Output directory', default='')
    parser_generate.add_argument('-N', '--name', type=str, help='Name of the datapack', default='')
    parser_generate.add_argument('-n', '--namespace', type=str, help='Custom namespace name', default='')
    parser_generate.add_argument('-d', '--description', type=str, help='The description of the datapack', default='')
    parser_generate.add_argument('-f', '--pack-format', type=int,
                                 help='Pack format (keeps track of compatible versions)', default=0)
    args = parser.parse_args()

    args_dict = {key.replace('-', '_'): val for key, val in vars(args).items()}
    if args.command is None:
        parser.print_help()
    elif args.command.startswith('c'):
        comp(**args_dict)
    else:
        gen_template(**args_dict)


if __name__ == '__main__':
    main()
