#!/usr/bin/env python3
import inspect
import json
import os
import re
import shutil
import zipfile
import sys

EXTENSION = 'dps'
SETTINGS = 'settings.json'

open(SETTINGS, 'a+').close()


def save_settings():
    with open(SETTINGS, 'w+') as write:
        json.dump(settings, write)


with open(SETTINGS, 'r+') as read:
    try:
        settings = json.load(read)
    except json.decoder.JSONDecodeError as e:
        print('Failed to load settings.json:', e, file=sys.stderr)
        settings = {'input': '.', 'output': 'output'}
        save_settings()
        print('Settings set to default values')


def get_menu():
    def comp():
        """c - Compile"""
        for namespace in os.listdir(os.path.join(settings['input'], 'data')):
            files = {'': []}
            function_tags = {}
            other = {}

            def __other__(s: str):
                return other.setdefault(s, {})

            fun_stack = ['']

            def __line__(ln: str):
                files[fun_stack[-1]].append(ln)

            def __function__(fun_name: str):
                if fun_stack[-1] == fun_name:
                    fun_stack.pop()
                    return False
                else:
                    fun_stack.append(fun_name)
                    return True

            if not settings['input']:
                settings['input'] = '.'
            data = os.path.join(settings['input'], 'data')
            if os.path.exists(data):
                is_zip = settings['output'].endswith('.zip')
                if is_zip:
                    output_folder = settings['output'][:-4]
                else:
                    output_folder = settings['output']
                shutil.rmtree(output_folder)
                shutil.copytree(data, os.path.join(output_folder, 'data'))
                shutil.copy(os.path.join(settings['input'], 'pack.mcmeta'),
                            os.path.join(output_folder, 'pack.mcmeta'))

            else:
                raise FileNotFoundError('need data folder and pack.mcmeta')
            working_folder = os.path.join(settings['input'], f'data/{namespace}/sources')
            for filename in os.listdir(working_folder):
                if filename.endswith(f'.{EXTENSION}'):
                    command_line = re.compile(r'([\t ]*)/(.*)')
                    interpolation = re.compile(r'\$\{\{.*?}}')
                    create_statement = re.compile(r'([\t ]*)create\b[ \t]*([\w/]+)\b[ \t]*([a-z\d:/_-]*)\b(.*)')
                    code = []
                    # concat_line = None
                    with open(os.path.join(working_folder, filename), 'r') as r:
                        for line in r:
                            # <editor-fold defaultstate="collapsed" desc="allow \ at the end of a line for concat">

                            # if concat_line is not None:
                            #     line = f'{concat_line} {line}'
                            #     concat_line = None
                            # if line.endswith('\\'):
                            #     concat_line = line[:-1]
                            #     continue

                            # </editor-fold>

                            found = command_line.match(line)
                            if found:
                                spacing, contents = found.group(1), found.group(2)
                                q = '"""' if contents.endswith("'") else "'''"
                                # replace { and } with other sequences, so they don't interfere with f string
                                contents = contents.replace('{', '{{').replace('}', '}}')
                                # replace interpolation with value
                                contents = interpolation.sub(r"{\1}", contents)
                                extra_line = None
                                if contents.endswith(':'):
                                    i = contents.rindex('function')
                                    f_pat = re.compile(
                                        r'function\b[ \t]*([a-z\d:/_-]*)\b[\t ]*(?:\[([a-z\d:/_, -]*)])?[\t ]*:')
                                    match = f_pat.match(contents[i:])
                                    func_names, tags = match.group(1), match.group(2)
                                    if func_names == '':
                                        func_names = f'{namespace}:function'
                                    if ':' not in func_names:
                                        func_names = f'{namespace}:{func_names}'
                                    if func_names in files:
                                        x = 1
                                        while f'{func_names}_{x}' in files:
                                            x += 1
                                        func_names = f'{func_names}_{x}'
                                    files[func_names] = []
                                    if tags != '':
                                        for tag in tags.split(','):
                                            tag = tag.strip()
                                            if ':' not in tag:
                                                tag = f'minecraft:{tag}'
                                            function_tags.setdefault(tag, []).append(func_names)
                                    extra_line = f'{spacing}while __function__("{func_names}"):'
                                    contents = f'{contents[:i]}function {func_names}'
                                code.append(f"{spacing}__line__(f{q}{contents}{q})")
                                if extra_line:
                                    code.append(extra_line)
                            else:
                                create = create_statement.match(line)
                                if create:
                                    spacing, file_type, name, data = \
                                        create.group(1), create.group(2), create.group(3), create.group(4)
                                    if ':' not in name:
                                        name = f'{namespace}:{name}'
                                    code.append(f'{spacing}__other__("{file_type}")["{name}"] = {data}')
                                else:
                                    code.append(line[:-1])
                    print(filename)
                    print('\n'.join(code))
                    exec('\n'.join(code), {}, {'__line__': __line__,
                                               '__function__': __function__,
                                               '__other__': __other__})
            files.pop('')
            # Iterate through generated functions
            for name, content in files.items():
                path = os.path.join(output_folder, f'data/{name.replace(":", "/functions/")}.mcfunction')
                try:
                    os.makedirs(os.path.dirname(path))
                except FileExistsError:
                    pass
                with open(path, 'w') as w:
                    w.write('\n'.join(content))

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
                        if isinstance(content, dict):
                            json.dump(content, w)
                        elif isinstance(content, str):
                            w.write(content)
                        else:
                            w.write('\n'.join(content))
            if is_zip:
                def zipdir(path1, ziph):
                    # ziph is zipfile handle
                    for root, dirs, files1 in os.walk(path1):
                        for file in files1:
                            ziph.write(os.path.join(root, file),
                                       os.path.relpath(os.path.join(root, file),
                                                       os.path.dirname(path1)))

                zipf = zipfile.ZipFile(settings['output'], 'w', zipfile.ZIP_DEFLATED)
                zipdir(os.path.join(output_folder, 'data'), zipf)
                zipf.write(os.path.join(output_folder, 'pack.mcmeta'), 'pack.mcmeta')
                zipf.close()
                shutil.rmtree(output_folder)

    def view():
        """v - View Settings"""
        print(settings)

    def gene():
        """g - Generate Template"""
        print("All of the following fields have defaults:")
        namespace = input('Namespace (all lowercase): ') or 'main'
        name = input('Datapack Name: ') or 'Datapack'
        desc = input('Description: ') or 'The default data for Minecraft'
        pack_format = int(input('Pack Format: ') or '15')
        sources = os.path.join(settings['input'], f'data/{namespace}/sources')
        try:
            os.makedirs(sources)
        except FileExistsError:
            pass
        with open(os.path.join(os.path.join(sources, f'main.{EXTENSION}')), 'w') as w:
            w.write(inspect.cleandoc(f"""
                /function tick [tick]:
                    pass
                /function load [load]:
                    /say loaded {name}"""))

        with open(os.path.join(settings['input'], 'pack.mcmeta'), 'w') as w:
            json.dump({
                "pack": {
                    "pack_format": pack_format,
                    "description": desc,
                    "name": name
                }
            }, w)

    def outp():
        """o - Change Output Directory"""
        print(f'Current Output Directory: {settings["output"]}')
        print('"clear" for default, and nothing to change nothing')
        print('End with .zip to export as zip')
        option = input('New Directory: ').strip()
        if option == 'clear':
            settings['output'] = '.'
        elif option != '':
            settings['output'] = option
        save_settings()

    def inpu():
        """i - Change Input Directory"""
        print(f'Current Directory: {settings["input"]}')
        print('"clear" for default, and nothing to change nothing')
        option = input('New Directory: ').strip()
        if option == 'clear':
            settings['input'] = '.'
        elif option != '':
            settings['input'] = option
        save_settings()

    def qui():
        """q - Quit"""
        return True

    # Dictionaries maintain order
    return {func.__doc__[0]: func for func in [comp, view, gene, outp, inpu, qui]}


menu_dict = get_menu()


def menu():
    print('Packscript menu:')
    for func in menu_dict.values():
        print(func.__doc__)
    letter = input("Choice: ")
    return (menu_dict.get(letter) or (lambda: None))()


def main():
    # noinspection PyGlobalUndefined
    global menu
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if not (func := menu_dict.get(arg)):
                raise RuntimeError(f"didn't understand argument {arg}")
            else:
                if func() is not None:
                    def menu(): return True
    while menu() is None:
        pass


if __name__ == '__main__':
    main()
