#!/usr/bin/env python3

# /// script
# requires-python = ">=3.12"
# ///
__version__ = '0.2.4'
__v_type__  = 'release'
__author__  = 'Slackow'
__license__ = 'MIT'

# # # # # # # # # # # # # # # # # # # # # #
# Please set this to your username if you are modifying this script
modified_by = ''
# # # # # # # # # # # # # # # # # # # # # #

latest_mc_version = '1.21.6'

import textwrap, argparse, json, re, sys, shutil, tempfile
from os import chdir
from pathlib import Path


def ver(base_version, start, end, *, pf):
    return {f'{base_version}.{x}': pf for x in range(start, end + 1)}


pack_formats = {
    'future': 9001,
    '1.21.6': 80,
    '1.21.5': 71,
    '1.21.4': 61,
    '1.21.3': 57, '1.21.2': 57,
    '1.21.1': 48, '1.21': 48,
    '1.20.6': 41, '1.20.5': 41,
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

DATA_EXT = 'dps'
FUNC_EXT = 'fps'

if __v_type__ not in ('release', 'dev'):
    raise AssertionError(f'Version type {__v_type__!r} is invalid')


def ns(resource: str, /, *, default: str = 'minecraft'):
    return resource if ':' in resource else f'{default}:{resource}'


namespace_re = re.compile(r'[a-z0-9-_.]+')
func_re = re.compile(r'(?<!-)\bfunction\b(?!-)')


def right_most_function(contents):
    # Use finditer to get match objects, which include the start and end positions of each match
    matches = list(func_re.finditer(contents))
    return matches[-1].end() if matches else None


def version_or_pf(s: str, default=...):
    res = pack_formats.get(s)
    if res:
        return res
    try:
        return int(s)
    except ValueError as e:
        if default is not ...:
            return default
        raise e


def build_globals(func_stack: list, capturer_stack: list, func_files: dict,
                  other: dict, namespace='minecraft', function_tags=None):
    def __other__(s: str) -> dict:
        return other.setdefault(s, {})

    def __line__(ln: str):
        if capturer_stack:
            capturer_stack[-1].append(ln)
        else:
            func_files[func_stack[-1]].append(ln)

    func_def_re = re.compile(r'^([a-z\d:/_-]*)[ \t]*(?:\[([a-z\d:/_, -]*)](.*))?$')

    def __function_name__(func_def: str) -> (str, str):
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
        return func_name, (extra or '')

    class FuncContext:
        def __init__(self, func_name: str):
            self.func_name = func_name

        def __enter__(self):
            func_stack.append(self.func_name)

        def __exit__(self, exc_type, exc_val, exc_tb):
            func_stack.pop()

        def replace(self):
            func_stack[-1] = self.func_name

    def __function__(func_name: str) -> FuncContext:
        return FuncContext(func_name)

    class Capturer:
        def __enter__(self):
            capturer = []
            capturer_stack.append(capturer)
            return capturer

        def __exit__(self, *_):
            capturer_stack.pop()

    def capture_lines() -> Capturer:
        return Capturer()

    def n(s: str) -> str:
        return ns(s.removesuffix('.json'), default=namespace)

    class Dp:
        def __init__(self, type: tuple[str, ...]=()):
            self._type = type
        def __getattr__(self, attr: str):
            if '/'.join(self._type) in other:
                return other['/'.join(self._type)][n(attr)]
            return Dp((*self._type, attr))
        def __setattr__(self, attr: str, value: dict | list | str | bytes):
            if attr == '_type':
                object.__setattr__(self, attr, value)
                return
            other.setdefault('/'.join(self._type), {})[n(attr)] = value
        def __delattr__(self, item):
            other['/'.join(self._type)].pop(n(item))
        def __getitem__(self, item: tuple[str, str] | str):
            if self._type:
                return other['/'.join(self._type)][n(item)]
            type, resource = item
            return other[type][n(resource)]
        def __setitem__(self, item: tuple[str, str] | str, value: dict | list | str | bytes):
            if self._type:
                other.setdefault('/'.join(self._type), {})[n(item)] = value
                return
            type, resource = item
            other.setdefault(type, {})[n(resource)] = value
        def __delitem__(self, key):
            other['/'.join(self._type)].pop(n(key))

    dp = Dp()
    funcs = [__other__, __line__, __function_name__, __function__, capture_lines]
    return {func.__name__: func for func in funcs} | {'ns': namespace, 'dp': dp}


def get_header() -> str:
    return f'# Generated by PackScript {__version__}-{__v_type__} by {__author__}{modified_by and f" modified by: {modified_by}"}\n'


def get_folder(path: str, pf: int) -> str:
    return path if pf >= 45 else path + 's'


def read_pack_meta(input: Path) -> dict:
    if not (input / 'pack.mcmeta').is_file():
        raise FileNotFoundError('No pack.mcmeta found')
    try:
        pack_meta = json.loads((input / 'pack.mcmeta').read_text())
    except ValueError:
        pack_meta = None
    if not pack_meta or not isinstance(pack_meta.get('pack'), dict):
        raise ValueError('Invalid pack.mcmeta file')
    return pack_meta


def comp_file(output_folder: Path, parent: Path, filename: Path, globals: dict[str, object], verbose=False):
    command_re = re.compile(r'([\t ]*)/(.*)')
    interpolation_re = re.compile(r'\$\{\{(.*?)}}|(?<!^)\$([a-zA-Z_]\w*)')
    create_statement_re = re.compile(r'([\t ]*)create\b[ \t]*([\w/]+)\b[ \t]*([a-z\d:/_.-]*)[ \t]*->(.*)')
    code = []
    concat_line = None
    curr_file = parent / filename
    print(filename.relative_to(output_folder))
    for line in curr_file.read_text().splitlines():
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
            if (end_chr := contents[-1:]) in (':', ';'):
                func_def_start = right_most_function(contents)
                # print('func: ', line)
                if func_def_start is None:
                    raise ValueError(f'Command {contents!r} ends with colon/semicolon but does not contain function')
                func_def = contents[func_def_start:-1].strip()
                code.append(f'{indent}__f, __extra = __function_name__(f"{func_def}")')
                contents = f'{contents[:func_def_start]} {{__f}}{{__extra}}'
                extra_line = f'{indent}with __function__(__f):'
                if end_chr == ';':
                    extra_line = f'{indent}__function__(__f).replace()'
            code.append(f'{indent}__line__(rf""" {contents} """[1:-1])')
            if extra_line:
                code.append(extra_line)
        else:
            create_match = create_statement_re.fullmatch(line)
            if create_match:
                indent, file_type, name, data = create_match.groups()
                name = ns(name, default=str(globals['ns']))
                code.append(f'{indent}__other__("{file_type}")["{name}"] ={data}')
            else:
                code.append(line)
    pyth = '\n'.join(code)

    def print_code(file=sys.stdout):
        max_len = len(str(len(code)))
        for i, ln in enumerate(code, start=1):
            print(f'{i:>{max_len}}: {ln}', file=file)

    if verbose:
        print_code()
    old_path = sys.path[:]
    sys.path.insert(0, str(curr_file.parent))
    try:
        exec(pyth, globals)
    except Exception as e:
        print('Error in:', filename, file=sys.stderr)
        print_code(sys.stderr)
        raise e
    finally:
        sys.path = old_path


def comp_pack(output_folder, pack_format, source, verbose, overlay=False):
    function_tags: dict[str, list[str]] = {}
    other: dict[str, dict[str, object]] = {}
    for namespace in sorted((output_folder / 'data').iterdir()):
        namespace: Path
        func_files: dict[str, list[str]] = {'': []}
        func_stack: list[str] = ['']
        capturer_stack: list[str] = []

        globals = build_globals(func_stack, capturer_stack, func_files, other, namespace.name, function_tags)
        working_folder = (namespace / get_folder("source", pack_format))
        if (not get_folder('source', pack_format).endswith('s') and
                (namespace / 'sources').exists()):
            raise ValueError('Legacy "sources" folder detected! Rename your folders to be singular!')

        for filename in sorted(working_folder.rglob(f'*.{DATA_EXT}')):
            base = output_folder.parent if overlay else output_folder
            comp_file(base, working_folder, filename, globals, verbose=verbose)

        if not source:
            shutil.rmtree(namespace / get_folder('source', pack_format), ignore_errors=True)
        func_files.pop('')
        # Iterate through generated functions
        for name, content in func_files.items():
            func_dir = get_folder('function', pack_format)
            mcfunction_path = output_folder / 'data' / f'{name.replace(":", f"/{func_dir}/")}.mcfunction'
            if not content:
                continue
            mcfunction_path.parent.mkdir(parents=True, exist_ok=True)
            mcfunction_path.write_text(get_header() + '\n'.join(content) + '\n')

        other.setdefault(f'tags/{get_folder("function", pack_format)}', {}).update(
            {tag: {'values': func_names} for tag, func_names in function_tags.items()})

        # Write stuff in other
        for file_type, stuff in other.items():
            for name, content in stuff.items():
                name = name.replace(':', f'/{file_type}/')
                if '.' not in name:
                    name += '.json'
                other_path = output_folder / 'data' / name
                other_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, (dict, list)):
                    content = json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True)
                if not isinstance(content, (str, bytes)):
                    raise ValueError(f'Error: invalid content: {content!r}')
                if isinstance(content, bytes):
                    other_path.write_bytes(content)
                else:
                    other_path.write_text(content)


def comp(*, input: str, output: str, verbose: bool, source: bool, **_):
    input: Path = Path(input or '.').absolute()
    has_datapack = (input / 'data').is_dir()

    is_jar = output.endswith('.jar')
    is_zip = output.endswith('.zip')
    final_output_folder = Path(output.removesuffix('.zip').removesuffix('.jar')).absolute()
    if not final_output_folder.stem:
        raise ValueError('Please provide an output with a filename')
    if input == final_output_folder:
        raise shutil.SameFileError('Input and output directories must not have the same')

    # Create a temporary directory for building
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_output = Path(temp_dir) / final_output_folder.name
        temp_output.mkdir(parents=True, exist_ok=True)

        if has_datapack:
            data = input / 'data'
            if not data.exists() or not (input / 'pack.mcmeta').exists():
                raise FileNotFoundError('Need data folder and pack.mcmeta')
            if is_jar and not any((input / m).exists() for m in ('fabric.mod.json', 'mods.toml', 'neoforge.mods.toml')):
                raise FileNotFoundError(f'Need "fabric.mod.json" and/or "mods.toml" and/or '
                                        f'"neoforge.mods.toml" Use {sys.argv[0]} init --modded')

            def config(loc: str, *, dst='', mkdirs=False, dirs_exist_ok=False) -> bool:
                type = 'dir' if loc.endswith('/') else 'file'
                src = input / loc
                dst = temp_output / (dst or loc)
                if not (src.is_file() if type == 'file' else src.is_dir()):
                    if src.exists():
                        raise (IsADirectoryError if type == 'file' else NotADirectoryError)(loc)
                    return False
                if mkdirs:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                if type == 'file':
                    shutil.copy(src, dst)
                else:
                    shutil.copytree(src, dst, dirs_exist_ok=dirs_exist_ok)
                return True

            has_overlays = config('overlays/', dst='.', dirs_exist_ok=True)
            config('data/')
            config('pack.png')
            if is_jar:
                config('assets/')
                config('fabric.mod.json')
                config('mods.toml', dst='META-INF/mods.toml', mkdirs=True)
                config('mods.toml', dst='META-INF/neoforge.mods.toml')
                config('neoforge.mods.toml', dst='META-INF/neoforge.mods.toml', mkdirs=True)
            pack_meta = read_pack_meta(input)
            pack_format = pack_meta.get('pack').get('pack_format')
            if not isinstance(pack_format, int):
                raise ValueError('Invalid pack.mcmeta file')
            comp_pack(temp_output, pack_format, source, verbose)
            if has_overlays:
                registered_overlays = pack_meta.setdefault('overlays', {}).setdefault('entries', [])
                overlay_re = re.compile(r'([\d.]+)-([\d.]+|future)')
                for overlay in sorted((input / 'overlays').iterdir()):
                    if overlay.name in (reg['directory'] for reg in registered_overlays):
                        continue
                    elif overlay_match := overlay_re.fullmatch(overlay.name.replace('_', '.')):
                        min, max = map(version_or_pf, overlay_match.groups())
                        formats = {'min_inclusive': min, 'max_inclusive': max}
                    elif pf := version_or_pf(overlay.name.replace('_', '.'), default=False):
                        formats = pf
                    else:
                        raise ValueError(f'Unregistered overlay {overlay.name!r}, add it to pack.mcmeta or name it '
                                         f'after the version(s) it is for (1_20_2, 1_20_3-1_20_5)')
                    registered_overlays.insert(0, {
                        'formats': formats,
                        'directory': overlay.name,
                    })
                for overlay in registered_overlays:
                    path = temp_output / overlay['directory']
                    comp_pack(path, pack_format, source, verbose, overlay=True)
            (temp_output / 'pack.mcmeta').write_text(json.dumps(pack_meta, indent=4))

        func_files = {}
        for f in sorted(input.glob(f'*.{FUNC_EXT}')):
            func_stack = [f.name]
            func_files[f.name] = []
            globals = build_globals(func_stack, [], func_files, {})

            comp_file(input, input, f, globals, verbose=verbose)
        if func_files:
            temp_output.mkdir(parents=True, exist_ok=True)
        for f, content in func_files.items():
            f = f[f.find(':') + 1:].replace('/', '_').removesuffix(f'.{FUNC_EXT}')
            mcfunction_path = temp_output / f'{f}.mcfunction'
            mcfunction_path.write_text(get_header() + '\n'.join(content) + '\n')
        if not func_files and not has_datapack:
            print("No datapack/func_files found!")
            return

        if is_zip or is_jar:
            cwd = Path.cwd()
            try:
                chdir(temp_dir)
                shutil.make_archive(temp_output.name, 'zip', temp_output.name)
                if is_jar:
                    zip_path = Path(temp_dir) / f"{temp_output.name}.zip"
                    jar_path = final_output_folder.parent / f"{final_output_folder.name}.jar"
                    shutil.copy(zip_path, jar_path)
                else:
                    zip_path = Path(temp_dir) / f"{temp_output.name}.zip"
                    final_zip_path = final_output_folder.parent / f"{final_output_folder.name}.zip"
                    shutil.copy(zip_path, final_zip_path)
            finally:
                chdir(cwd)
        else:
            if final_output_folder.exists():
                for item in final_output_folder.iterdir():
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    else:
                        shutil.rmtree(item)
            else:
                final_output_folder.mkdir(parents=True, exist_ok=True)

            for item in temp_output.iterdir():
                if item.is_file():
                    shutil.copy2(item, final_output_folder / item.name)
                else:
                    shutil.copytree(item, final_output_folder / item.name, dirs_exist_ok=True)


def init_modded_template(name: str, description: str, output: Path, namespace: str):
    (output / 'fabric.mod.json').write_text(json.dumps({
        "schemaVersion": 1,
        "id": namespace,
        "version": "1.0",
        "name": name,
        "description": description,
        "authors": [],
        "depends": {
            "minecraft": "*"
        },
        "icon": "pack.png"
    }, indent=4, sort_keys=True))
    (output / 'mods.toml').write_text(textwrap.dedent(f'''
        # By default 'mods.toml' will be copied to 'neoforge.mods.toml' as well, 
        # Create a separate 'neoforge.mods.toml' to override values here
        modLoader="lowcodefml"
        loaderVersion="[1,)"
        license="All Rights Reserved"
        showAsResourcePack=false
        showAsDataPack=false

        [[mods]]
        modId="{namespace}"
        version="1.0"
        description="""{description}"""
        logoFile="pack.png"
        authors=""
    '''.lstrip('\n')))


def init_template(*, name: str, description: str, pack_format: int, output: str, modded: bool | None, namespace: str, **_):
    if modded and (Path(output or '.') / 'pack.mcmeta').is_file():
        path = Path(output or '.')
        meta = read_pack_meta(path)
        description = description or meta.get('pack', {}).get('description')
        if not (description and isinstance(description, str)):
            description = input('Description ():')
        namespaces = [d.name for d in (path / 'data').iterdir() if d.is_dir() and d.name != 'minecraft']
        default_ns = namespaces and namespaces[0]
        namespace = namespace  or input(f'Namespace ({default_ns}): ') or default_ns
        def_name = path.parent.resolve().name
        name = name or input(f'Name ({def_name}):') or def_name
        init_modded_template(name, description, path, namespace)
        return
    if not all((name, description, pack_format, output, namespace)):
        print('Leave a field empty to have it set to its default value')
    name = name or input('Datapack Name (Datapack): ') or 'Datapack'
    def_ns = re.sub(r'\W', '-', name.lower().replace(' ', '_'))
    namespace = namespace or input(f'Namespace ({def_ns}): ') or def_ns
    namespace = re.sub(r'\W', '-', namespace.lower().replace(' ', '_'))
    if not namespace_re.fullmatch(namespace):
        raise ValueError(f'Namespace must match regex: /{namespace_re.pattern}/ ({namespace} does not match)')
    v = ''
    while not pack_format:
        v = input(f'Pack Format/Minecraft Version ({latest_mc_version}): ') or latest_mc_version
        try:
            pack_format = version_or_pf(v)
        except ValueError:
            print(f"You must provide a recognized mc version or a pack format, {v!r} is neither.")
    v = v and f' for version {v}'
    description = description or input(f'Description (Datapack {name!r}{v}): ') or \
                  f'Datapack {name!r}{v}'
    modded = modded if modded is not None else input('Add modded metadata for '
                                                     'forge/fabric/neoforge? y/n (n): ')[:1].lower() == 'y'
    output: str = output or input(f'Output Directory ({name.replace(" ", "_")}): ') or name.replace(' ', '_')
    output: Path = Path(output).absolute()
    if (output / 'data').exists() or (output / 'pack.mcmeta').exists():
        raise ValueError('data or pack.mcmeta already present in this directory, '
                         'remove them to generate the template, or specify a different directory.')
    source = (output / 'data' / namespace / get_folder("source", pf=pack_format))
    source.mkdir(parents=True, exist_ok=True)
    (source / f'main.{DATA_EXT}').write_text(textwrap.dedent(f'''
        /function tick [tick]:
            /seed
        /function load [load]:
            /tellraw @a "Loaded {name}"
    '''.lstrip('\n')))
    (output / 'pack.mcmeta').write_text(json.dumps({
        'pack': {
            'pack_format': pack_format,
            'supported_formats': {'min_inclusive': pack_format, 'max_inclusive': pack_format},
            'description': description
        }
    }, indent=4, sort_keys=True))
    if modded:
        init_modded_template(name, description, output, namespace)


def update_pack_format(*, input: str, target: str, min: str, max: str, **_):
    input: Path = Path(input).absolute()
    pack_meta = read_pack_meta(input)
    target_pack_format = pack_meta.get('pack').get('pack_format')
    if not isinstance(target_pack_format, int):
        raise ValueError('Invalid pack.mcmeta file')
    match pack_meta.get('pack').get('supported_formats'):
        case [min_pack_format, max_pack_format]: pass
        case {'min_inclusive': min_pack_format, 'max_inclusive': max_pack_format}: pass
        case _: min_pack_format, max_pack_format = None, None
    if target or min or max:
        from builtins import min as min_f, max as max_f
        target = version_or_pf(target, target_pack_format)
        min = min_f(version_or_pf(min, min_pack_format) or target, target)
        max = max_f(version_or_pf(max, max_pack_format) or target, target)
        pack_meta.get('pack')['supported_formats'] = {'min_inclusive': min, 'max_inclusive': max}
        pack_meta.get('pack')['pack_format'] = target
        (input / 'pack.mcmeta').write_text(json.dumps(pack_meta, indent=4, sort_keys=True))
    else:
        target, min, max = target_pack_format, min_pack_format, max_pack_format
        print('edit these values via the --min, --target, or --max options')

    def versions_of(pf):
        return f"({', '.join(key for key, value in pack_formats.items() if value == pf)})"

    def c(s: str) -> str:
        """ color numbers in a string with ansi codes """
        return re.sub(r'(\d+)', '\033[33m\\1\033[0m', s)

    if max:
        print(c(f"{'max pack_format:':<20}{max:3} {versions_of(max)}"))
    print(c(f"{'target pack_format:':<20}{target:3} {versions_of(target)}"))
    if min:
        print(c(f"{'min pack_format:':<20}{min:3} {versions_of(min)}"))


# <editor-fold defaultstate="collapsed" desc="def update(): ...">
def get_data_from_url(url: str, max_redirects=10):
    import ssl
    from http.client import HTTPSConnection
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = HTTPSConnection(parsed_url.netloc, context=context)
    path = parsed_url.path + ((parsed_url.query and f"?{parsed_url.query}") or "")
    headers = {'Accept': '*/*', 'User-Agent': 'packscript.py'}
    connection.request('GET', path, headers=headers)
    response = connection.getresponse()
    if 300 <= response.status < 400 and max_redirects > 0:
        return get_data_from_url(response.getheader('Location'), max_redirects - 1)
    return response


def get_latest_version() -> str:
    url = 'https://api.github.com/repos/Slackow/PackScript/releases/latest'
    response = get_data_from_url(url)
    if response.status == 200:
        data = response.read()
        json_data = json.loads(data.decode('utf-8'))
        return json_data['tag_name']
    else:
        raise IOError(f'Could not get latest version \nstatus: {response.status}\nbody: {response.read()}')


def replace_script_with_latest():
    print("Updating PackScript...")
    url = 'https://github.com/Slackow/PackScript/releases/latest/download/packscript.py'
    response = get_data_from_url(url)
    if response.status == 200:
        data = response.read()
        if b'\n__version__ = ' in data:
            Path(sys.argv[0]).write_bytes(data)
            print("Done!")
            return
        print(data, file=sys.stderr)
        raise ValueError("Bad data returned")
    else:
        raise IOError(f'Could not get packscript.py \nstatus: {response.status}\nbody:{response.read()}')


def update():
    if __package__ is not None:
        print('You are using pip! Cannot update.')
        print('To update the package via pip use "pip install --upgrade packscript"')
        return
    if getattr(sys, 'frozen', False):
        print('The script is frozen! (embedded in an exe or zip etc.) Cannot update.')
        return
    latest = get_latest_version()
    if latest == __version__:
        print(f"Up to date, PackScript {__version__}")
        return
    print(f"Latest version of PackScript is {latest}, you have {__version__}.")
    if [int(x) for x in latest.split('.')] < [int(x) for x in __version__.split('.')]:
        print("You have a future version, not updating.")
        return
    replace_script_with_latest()
# </editor-fold>


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
    parser_compile.add_argument('-o', '--output', type=str, help='Output directory/zip', default='output')
    parser_compile.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_compile.add_argument('-v', '--verbose', help='Print generated Python code.', default=False,
                                action='store_true')
    parser_compile.add_argument('-S', '--source', help='Include source files in output.', default=False,
                                action='store_true')

    # "init" command
    parser_init = subparsers.add_parser('init',
                                        help='Initialize datapack template (interactively). Accepts arguments.\n'
                                             '"packscript init --help" for more info',
                                        description='Initialize a new datapack template\n\n'
                                                    'Use this command to create a new datapack template, setting '
                                                    'up a basic structure for your project. '
                                                    'Information can be provided in args or interactively.',
                                        formatter_class=argparse.RawTextHelpFormatter)
    parser_init.add_argument('-o', '--output', type=str, help='Output directory', default='')
    parser_init.add_argument('-N', '--name', type=str, help='Name of the datapack', default='')
    parser_init.add_argument('-n', '--namespace', type=str, help='Custom namespace name', default='')
    parser_init.add_argument('-d', '--description', type=str, help='The description of the datapack', default='')
    parser_init.add_argument('-f', '--pack-format', type=int,
                             help='Pack format (keeps track of compatible versions)', default=0)
    parser_init.add_argument('-m', '--modded', help='Init modded config files, for fabric, forge, and neoforge',
                             action='store_true', default=None)
    parser_init.add_argument('--no-modded', action='store_false', dest='modded', help='Do not initialize any modded config files')

    # "pack_format" command
    parser_pack_format = subparsers.add_parser('pack_format', aliases=['pf'],
                                               help='Read and update pack_formats and see their associated versions, '
                                                    'pack format numbers/versions strings are interchangeable, '
                                                    'and min/max must be within the range of target',
                                               description="Update or view your pack's supported pack format versions.",
                                               formatter_class=argparse.RawTextHelpFormatter)
    parser_pack_format.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_pack_format.add_argument('-t', '--target', type=str, help='Set the target pack_format', default='')
    parser_pack_format.add_argument('-m', '--min', type=str, help='Set the minimum pack_format', default='')
    parser_pack_format.add_argument('-M', '--max', type=str, help='Set the maximum pack_format', default='')

    # "update" command
    subparsers.add_parser('update', aliases=['u'],
                          help='Check for PackScript updates, and update if found.',
                          description='Update PackScript if there is an update available.',
                          formatter_class=argparse.RawTextHelpFormatter)

    args = parser.parse_args()

    args_dict = {key.replace('-', '_'): val for key, val in vars(args).items()}
    if args.version:
        print(f'PackScript {__version__}-{__v_type__}')
    elif args.command is None:
        parser.print_help()
    elif args.command.startswith('c'):
        comp(**args_dict)
    elif args.command.startswith('p'):
        update_pack_format(**args_dict)
    elif args.command.startswith('u'):
        update()
    else:
        try:
            init_template(**args_dict)
        except KeyboardInterrupt:
            print('\nInterrupted')
            sys.exit(130)


if __name__ == '__main__':
    main()
