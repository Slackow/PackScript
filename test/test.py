import filecmp
import os
import shutil
import sys
import unittest


def packscript(*args):
    args = [f"'{arg}'" for arg in args]
    os.system(f'uv run ../packscript.py {" ".join(args)}')


def read_mcfunction(filepath):
    """ Read a .mcfunction file, ignoring the first line and any blank lines. """
    with open(filepath, 'r') as file:
        return '\n'.join(line for line in file.readlines()[1:] if line.strip())


class TestPackScriptCompilation(unittest.TestCase):
    def setUp(self):
        """ Setup temporary directory for output. """
        self.temp_dir = "tests/temp_output"
        os.makedirs(self.temp_dir, exist_ok=True)

    def tearDown(self):
        """ Clean up after tests. """
        shutil.rmtree(self.temp_dir)

    def compare_mcfunction_files(self, file1, file2):
        """ Compare two .mcfunction files under specific conditions. """
        content1 = read_mcfunction(file1)
        content2 = read_mcfunction(file2)
        self.assertEqual(content1, content2, f"File contents do not match for {os.path.basename(file1)}")

    def deep_compare_dirs(self, dir1, dir2):
        """ Recursively compare the contents of two directories. """
        comp = filecmp.dircmp(dir1, dir2)
        self.assertListEqual(comp.left_only, [], f"Extra files or directories in {dir1}")
        self.assertListEqual(comp.right_only, [], f"Missing files or directories in {dir1}")
        for file in comp.diff_files:
            self.assertRegex(file, r'.*\.mcfunction', 'Differing non-mcfunction file')
            self.compare_mcfunction_files(os.path.join(dir1, file), os.path.join(dir2, file))
        # Recursively compare the content of matched subdirectories
        for common_dir in comp.common_dirs:
            self.deep_compare_dirs(os.path.join(dir1, common_dir), os.path.join(dir2, common_dir))

    def test_compile_datapack(self):
        """ Test the compilation of datapacks. """
        test_cases = os.listdir('tests/data')
        for case in test_cases:
            with self.subTest(case=case):
                input_dir = f'tests/data/{case}/input_pack'
                expected_output_dir = f'tests/data/{case}/output_pack'
                output_dir = os.path.join(self.temp_dir, case)

                # Run the packscript compiler
                packscript('compile', '-i', input_dir, '-o', output_dir)

                # Compare output directory with expected output directory
                self.deep_compare_dirs(output_dir, expected_output_dir)
        print(f'\nTested {len(test_cases)} cases')


if __name__ == '__main__':
    os.chdir(os.path.dirname(sys.argv[0]))
    unittest.main()
