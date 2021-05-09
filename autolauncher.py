from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import json
import logging
import os
import subprocess
import sys
from abc import abstractmethod
from time import strftime

CLUSTER_BASE_PATH = '/gpfs/projects/bsc70'

MC_PATH = CLUSTER_BASE_PATH + '/bin/mc'

root = logging.getLogger()
root.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
root.addHandler(handler)


class LauncherWriter(object):
    def __init__(self, configuration):
        self.configuration = configuration

    def launcher_code(self):
        return '\n'.join(self.launcher_headers()) + '\n\n' + \
               '\n'.join(self.launcher_command()) + '\n'

    @abstractmethod
    def launcher_headers(self):
        pass

    @abstractmethod
    def launcher_command(self):
        pass

    def ctag(self):
        if self.configuration.get('continue_commit_tag', '') != '':
            ctag_to_use = self.configuration['continue_commit_tag']
        else:
            ctag_to_use = '$CI_COMMIT_SHORT_SHA'

        return ctag_to_use

    def python_command(self):

        python_command = self.configuration['binary'] + ' ' + self.configuration['workdir'] + self.configuration['command'] + ' ' + \
                         self.configuration['args'] + ' --COMMIT_TAG ' + self.ctag()

        return python_command


class SlurmLauncherWriter(LauncherWriter):
    @abstractmethod
    def extra_headers(self):
        pass

    def launcher_headers(self):
        headers = [
            '#!/bin/bash',
            '#SBATCH --job-name={job_name}'.format(**self.configuration),
            '#SBATCH --chdir={workdir}'.format(**self.configuration),
            '#SBATCH --output={output_filename}_%j_out.txt'.format(**self.configuration),
            '#SBATCH --error={error_filename}_%j_err.txt'.format(**self.configuration),
            '#SBATCH --ntasks={ntasks}'.format(**self.configuration),
            '#SBATCH --qos={qos}'.format(**self.configuration),
            '#SBATCH --time={time}'.format(**self.configuration),
        ]
        if self.configuration.get('nodes'):
            headers.append('#SBATCH --nodes={nodes}'.format(**self.configuration))
        if self.configuration.get('cpus-per-task'):
            headers.append('#SBATCH --cpus-per-task={cpus-per-task}'.format(**self.configuration))
        if self.configuration.get('tasks-per-node'):
            headers.append('#SBATCH --tasks-per-node={tasks-per-node}'.format(**self.configuration))
        if self.configuration.get('ntasks-per-SlurmLauncherWriter'):
            headers.append('#SBATCH --ntasks-per-socket={ntasks-per-socket}'.format(**self.configuration))
        if self.configuration.get('exclusive'):
            headers.append('#SBATCH --exclusive')

        headers = headers + self.extra_headers()

        return headers


class MNLauncherWriter(SlurmLauncherWriter):
    def extra_headers(self):
        headers = []
        if self.configuration.get('highmem'):
            headers.append('#SBATCH --constraint=highmem')

        return headers

    def launcher_command(self):
        command = ['export PYTHONPATH=src']
        command.append('export SINGULARITYENV_AWS_ACCESS_KEY_ID="$MINIO_ACCESS_KEY"')
        command.append('export SINGULARITYENV_AWS_SECRET_ACCESS_KEY="$MINIO_SECRET_KEY"')
        command.append('export SINGULARITYENV_MINIO_DOMAIN=https://localhost:9000')
        command.append('export SINGULARITYENV_SSEC_KEY=$SSEC_KEY')
        command.append('export SINGULARITYENV_ZIP_KEY=$ZIP_KEY')
        command.append('export CI_COMMIT_SHORT_SHA=$CI_COMMIT_SHORT_SHA')

        # temp fix from support:
        command.append('unset TMPDIR')


        SINGULARITY_PATH = '/apps/SINGULARITY/' + params['singularity_version'] + '/bin/singularity'
        SINGULARITY_BIND_PATH = '/gpfs/projects/bsc70/hpai/storage/data/:/gpfs/projects/bsc70/hpai/storage/data/'
        SINGULARITY_WRITABLE_PATH = params['containerdir']
        extra_flags = self.get_extra_singularity_flags()
        SINGULARITY_COMMAND = SINGULARITY_PATH + ' exec ' + ' ' + extra_flags + '\\\n' + \
                              ' -B ' + SINGULARITY_BIND_PATH + ' \\\n  --writable ' + \
                              SINGULARITY_WRITABLE_PATH + ' \\\n  bash -c "' + self.python_command() + '"'

        command.append(SINGULARITY_COMMAND)

        root.info('**LAUNCHING COMMAND** %s', str(command))

        return command

    def get_extra_singularity_flags(self):
        return ''


class P9LauncherWriter(SlurmLauncherWriter):
    def extra_headers(self):
        gres = self.configuration.get('gres')
        gres = int(gres) if gres else 1
        total_threads = self.configuration['ntasks'] * self.configuration['cpus-per-task']
        if gres * 40 > total_threads:
            raise Exception("Cluster P9 requires that ntasks*cpus-per-task >= gres*40, config: ntasks:",
                            self.configuration['ntasks'], ', cpus-per-task:', self.configuration['cpus-per-task'],
                            ', gres:', gres)
        return ['#SBATCH --gres=gpu:' + str(gres)]

    def launcher_command(self):
        P9_MODULES = ['ibm', 'openmpi/4.0.1', 'gcc/8.3.0', 'cuda/10.2', 'cudnn/7.6.4', 'nccl/2.4.8',
                      'tensorrt/6.0.1', 'fftw/3.3.8', 'ffmpeg/4.2.1', 'opencv/4.1.1', 'atlas/3.10.3',
                      'scalapack/2.0.2', 'szip/2.1.1', 'python/3.7.4_ML']

        command = ['module purge',
                   'module load ' + ' '.join(P9_MODULES),
                   'pip install pydicom-2.0.0-py3-none-any.whl',
                   'date',
                   'export PYTHONPATH=src',
                   self.python_command(),
                   'date']
        root.info('**LAUNCHING COMMAND** %s', str(command))

        return command


class AMDLauncher(MNLauncherWriter):
    def extra_headers(self):
        gres = self.configuration.get('gres')
        gres = int(gres) if gres else 1
        total_threads = self.configuration['ntasks'] * self.configuration['cpus-per-task']
        if gres * 40 > total_threads:
            pass
            # raise Exception("Cluster P9 requires that ntasks*cpus-per-task >= gres*40, config: ntasks:",
            #                self.configuration['ntasks'], ', cpus-per-task:', self.configuration['cpus-per-task'],
            #                ', gres:', gres)
        return ['#SBATCH --gres=gpu:' + str(gres)]

    def get_extra_singularity_flags(self):
        return '--rocm'


class MiniNLauncherWriter(LauncherWriter):
    def launcher_headers(self):
        raise NotImplementedError

    def launcher_command(self):
        raise NotImplementedError


LAUNCHER_WRITERS = {'mn4': MNLauncherWriter,
                    'p9': P9LauncherWriter,
                    'mini': MiniNLauncherWriter,
                    'amd': AMDLauncher}


# FUNCTIONS

def get_job_launcher_name(params):
    """
    Generate a non-repeated name for the launcher
    """
    num = 0
    current_commit = os.getenv('CI_COMMIT_SHORT_SHA', 'unknown')
    project = os.getenv('CI_PROJECT_PATH_SLUG', 'unknown')
    while True:
        job_name = (project + '_' + current_commit + '_{:03d}').format(num)
        job_name = job_name.replace('/', '_')
        filename = 'launcher_' + job_name + '.cmd'
        filepath = os.path.join(params['launchers_dir'], filename)
        if os.path.exists(filepath):
            num += 1
        else:
            break
    return job_name, filepath


def complete_params(params):
    if not params.get('launchers_dir'):
        params['launchers_dir'] = os.path.join(params['workdir'], 'launchers')

    if not params.get('output_dir'):
        params['output_dir'] = os.path.join(params['workdir'], 'output')

    job_name, launcher_filepath = get_job_launcher_name(params)
    if not params.get('job_name'):
        params['job_name'] = job_name
    if not params.get('launcher_filepath'):
        params['launcher_filepath'] = launcher_filepath

    if not params.get('output_filename'):
        params['output_filename'] = os.path.join(params['output_dir'], strftime('%Y%m%d%H%M%S') + '_' + job_name)

    if not params.get('error_filename'):
        params['error_filename'] = os.path.join(params['output_dir'], strftime('%Y%m%d%H%M%S') + '_' + job_name)

    return params


def make_dirs(params):
    dirs_2_create = ['launchers_dir', 'output_dir']
    for key in dirs_2_create:
        if not os.path.exists(params[key]):
            try:
                os.makedirs(params[key])
            except:
                root.warning(key + ' already exists: ' + params[key])


def write_launcher(configuration):
    launcher_for_machine = LAUNCHER_WRITERS[configuration['cluster']](configuration)

    # Write it
    text = launcher_for_machine.launcher_code()
    with open(configuration['launcher_filepath'], 'w') as launcher_file:
        launcher_file.write(text)


def launch_job(params):
    """
    Submit the file launcher_filepath
    """
    try:
        batch_cmd = 'sbatch ' + params['launcher_filepath']
        batch_stdout = subprocess.check_output(batch_cmd, shell=True)

        root.info('Job launched')
        root.info(batch_stdout)

        # Remove comment to cancel jobs
        # subprocess.call('scancel 11370504', shell=True)

        return batch_stdout
    except:
        root.error('Could not launch the job')


def create_and_launch(params):
    # Complete missing information with defaults
    params = complete_params(params)

    # Ensure required dirs exist
    make_dirs(params)

    root.info('Launcher path: ' + params['launcher_filepath'])
    root.info('Output dir: ' + params['output_dir'])

    # Write
    write_launcher(params)

    # Launch
    if 'nolaunch' not in params or params['nolaunch'] is None:
        launch_job(params)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Launch the experiments defined in the file provided')
    parser.add_argument('-f', '--file',
                        help='Path to the json file with experiments parameters',
                        default='/gpfs/projects/bsc70/hpai/storage/data/{{CLUSTER_WORKING_DIR}}/dataset_preprocessing.json')
    parser.add_argument('-w', '--workdir',
                        help='Path to the working directory for the job')
    parser.add_argument('-c', '--containerdir',
                        help='Path to the container directory to use as execution context')
    parser.add_argument('-l', '--singularity-version',
                        help='Version of singularity to use', default='3.6.4')
    parser.add_argument('-b', '--binary',
                        help='Binary to start execution (by default: python)', default='python')
    parser.add_argument('-n', '--nolaunch',
                        help='Only create, do not launch')

    args = parser.parse_args()
    with open(args.file) as f:
        params = json.load(f)
        params.update(vars(args))
        create_and_launch(params)
