import os
import shutil
import subprocess
import time

from memoized_property import memoized_property
import requests

from binder.settings import MainSettings
from binder.utils import namespace_params, fill_template, fill_template_string, make_dir
from binder.cluster import ClusterManager
from binder.indices import AppIndex
from binder.service import Service
from binder.log import *


class App(object):
    
    TAG = "App"

    index = AppIndex.get_index(MainSettings.ROOT)

    class BuildFailedException(Exception):
        pass

    class BuildState(object):
        BUILDING = "BUILDING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    @staticmethod
    def make_app_name(org, repo):
        return (org + "-" + repo).lower()

    @staticmethod
    def get_app(name=None):
        apps = App.index.find_apps()
        if not name:
            return [App(a) for a in apps.values()]
        app = apps.get(name)
        if app:
            return App(apps.get(name))
        return None

    @staticmethod
    def preload_all_apps():
        apps = App.get_app()
        cm = ClusterManager.get_instance()
        cm.preload_image("binder-base")
        for app in apps:
            cm.preload_image(app.name)

    @staticmethod
    def create(spec):
        return App(App.index.create(spec))

    @staticmethod
    def _get_deployment_id():
        return str(hash(time.time()))

    def __init__(self, meta):
        self._json = meta["app"]
        self.path = meta["path"]
        self.name = self._json.get("name")
        self.service_names = self._json.get("services", [])
        self.dependencies = map(lambda d: d.lower(), self._json.get("dependencies", []))
        self.repo_url = self._json.get("repo")

        # set once the repo is cloned
        self.repo = None

        self.app_id = App._get_deployment_id()

        # create the app directory
        self.dir = App.index.make_app_path(self)

    @memoized_property
    def services(self):
        return [Service.get_service(s_json["name"], s_json["version"]) for s_json in self.service_names]

    @property
    def build_state(self):
        return App.index.get_build_state(self)

    @property
    def last_build_time(self):
        return App.index.get_last_build_time(self)

    def get_app_params(self):
        # TODO some of these should be moved into some sort of a Defaults class (config file?)
        return namespace_params("app", {
            "name": self.name,
            "id": self.app_id,
            "notebooks-image": MainSettings.REGISTRY_NAME + "/" + self.name,
            "notebooks-port": 8888
        })

    def _fetch_repo(self):
        try:
            repo_path = os.path.join(self.dir, "repo")
            if requests.get(self.repo_url).status_code == 404:
                raise Exception("repository does not exist")
            cmd = ['git', 'clone', '--recursive', self.repo_url, repo_path]
            if os.path.isdir(repo_path):
                shutil.rmtree(repo_path)
            subprocess.check_call(cmd)
            self.repo = repo_path
        except Exception as e:
            error_log(self.TAG, "Could not fetch app repo: {}".format(e), app=self.name)
            raise App.BuildFailedException("could not fetch repository")

    def _get_base_image_name(self):
        return MainSettings.REGISTRY_NAME + "/" + "binder-base"

    def _get_image_name(self):
        return MainSettings.REGISTRY_NAME + "/" + self.name

    def _build_with_dockerfile(self, build_path):
        # build the app image from the repository's Dockerfile
        info_log(self.TAG, "Building the app image with Dockerfile...", app=self.name)
        app_img_path = os.path.join(build_path, "app")
        repo_path = os.path.join(app_img_path, "repo")
        repo_df_path = os.path.join(app_img_path, os.path.join(repo_path, "Dockerfile"))
        final_df_path = os.path.join(app_img_path, "Dockerfile")
        with open(final_df_path, "w+") as final_df:
            with open(repo_df_path, "r") as repo_df:

                def filter_from(line):
                    if line.startswith("FROM "):
                        # TODO very crude base image check
                        if not line.strip().endswith("/binder-base"):
                            msg = "Dockerfile base image is not binder-base. Building may fail."
                            warning_log(self.TAG, msg, app=self.name)
                        return False
                    return True

                lines = repo_df.readlines()
                no_from = filter(lambda line: filter_from(line), lines)

                # write the actual base image (with corrected registry)
                final_lines = ["FROM {}\n".format(self._get_base_image_name())] + no_from

                for line in final_lines:
                    final_df.write(line)
                final_df.write("\n")

                final_df.write("USER main\n")
                final_df.write("\n")
            
                # the dockerfile is building with the repository as its context
                notebook_path = self._json["notebooks"] if "notebooks" in self._json else "."
                final_df.write("ADD {0} $HOME/notebooks\n".format(notebook_path))
                final_df.write("\n")

                # write suffix lines to the app image
                nb_img_path = os.path.join(build_path, "suffix")
                with open(os.path.join(nb_img_path, "Dockerfile"), 'r') as nb_img:
                    for line in nb_img.readlines():
                        final_df.write(line)
                    final_df.write("\n")

        shutil.move(final_df_path, repo_df_path)

        # build the app image
        info_log(self.TAG, "Starting custom Dockerfile build (download logs for more details)",
                app=self.name)
        try:
            image_name = self._get_image_name().lower()
            cmd = ['docker', 'build', '-t', image_name, "--no-cache", os.path.join(app_img_path, "repo")]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            write_stream(self.TAG, "info", proc.stdout, app=self.name, no_publish=True)
            write_stream(self.TAG, "error", proc.stderr, app=self.name, no_publish=True)
            exit_code = proc.wait()
            if exit_code != 0:
                raise subprocess.CalledProcessError(exit_code, cmd=cmd)
        except subprocess.CalledProcessError as e:
           error_log(self.TAG, "Dockerfile build failed! (download logs for more details)",
                    app=self.name)
           raise App.BuildFailedException("could not build app {0}: {1}".format(self.name, e))
        info_log(self.TAG, "Completed custom Dockerfile build", app=self.name)

    def _build_without_dockerfile(self, build_path):
        # construct the app image Dockerfile
        app_img_path = os.path.join(build_path, "app")
        repo_path = os.path.join(app_img_path, "repo")
        info_log(self.TAG, "Building app image without Dockerfile...", app=self.name)
        with open(os.path.join(app_img_path, "Dockerfile"), 'w+') as app:

            app.write("FROM {}\n".format(self._get_base_image_name()))
            app.write("\n")

            for dependency in self.dependencies:
                # TODO do more modular dependency handling here
                if dependency == "requirements.txt":
                    shutil.copy(os.path.join(MainSettings.ROOT, "util", "handle-requirements.py"), os.path.join(app_img_path, "handle-requirements.py"))
                    app.write("ADD {} requirements.txt\n".format("repo/requirements.txt"))
                    app.write("ADD handle-requirements.py handle-requirements.py\n")
                    app.write("RUN python handle-requirements.py\n")
                    app.write("\n")
                elif dependency == "environment.yml":
                    app.write("ADD {0} environment.yml\n".format("repo/environment.yml"))
                    # see https://github.com/conda/conda-env/issues/166
                    # we override whatever name has been specified for the environment
                    app.write("RUN conda env create -n binder\n")
                    # so that we can explicitly activate it here
                    app.write("RUN echo \"export PATH=/home/main/anaconda/envs/binder/bin/:$PATH\" >> ~/.binder_start\n")
                    # ensure that the jupyter notebook is available in this environment
                    app.write("RUN conda install -n binder jupyter\n")
                    app.write("RUN /bin/bash -c \"source activate binder && jupyter kernelspec install-self --user\"\n")
                    app.write("\n")

            # if any services have client code, insert that now
            for service in self.services:
                client = service.client if service.client else ""
                app.write("# {} client\n".format(service.name))
                app.write(client)
                app.write("\n")

            notebook_path = self._json["notebooks"] if "notebooks" in self._json else "repo"
            app.write("ADD {0} $HOME/notebooks\n".format(notebook_path))
            app.write("\n")

            # write suffix lines to the app image
            nb_img_path = os.path.join(build_path, "suffix")
            with open(os.path.join(nb_img_path, "Dockerfile"), 'r') as nb_img:
                for line in nb_img.readlines():
                    app.write(line)
                app.write("\n")

        # build the app image
        try:
            image_name = self._get_image_name().lower()
            cmd = ['docker', 'build', '-t', image_name, "--no-cache", app_img_path]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            write_stream(self.TAG, "info", proc.stdout, app=self.name)
            write_stream(self.TAG, "error", proc.stderr, app=self.name)
            exit_code = proc.wait()
            if exit_code != 0:
                raise subprocess.CalledProcessError(exit_code, cmd=cmd)
        except subprocess.CalledProcessError as e:
            raise App.BuildFailedException("could not build app {0}: {1}".format(self.name, e))

    def _build_base_image(self):
        # make sure the base image is built
        info_log(self.TAG, "Building base image...", app=self.name)
        images_path = os.path.join(MainSettings.ROOT, "images")
        try:
            base_img = os.path.join(images_path, "base")
            image_name = self._get_base_image_name()
            subprocess.check_call(['docker', 'build', '-t', image_name, base_img])
            info_log(self.TAG, "Squashing and pushing {} to private registry...".format(image_name), app=self.name)
            subprocess.check_call([os.path.join(MainSettings.ROOT, "util", "squash-and-push"), image_name])
        except subprocess.CalledProcessError as e:
            error_log(self.TAG, "Could not build the base image: {}".format(e), app=self.name)
            raise App.BuildFailedException("could not build the base image")

    def _fill_templates(self, build_path):
        info_log(self.TAG, "Copying files and filling templates...", app=self.name)
        images_path = os.path.join(MainSettings.ROOT, "images")
        for img in os.listdir(images_path):
            img_path = os.path.join(images_path, img)
            bd_path = os.path.join(build_path, img)
            shutil.copytree(img_path, bd_path)
            for root, dirs, files in os.walk(bd_path):
                for f in files:
                    fill_template(os.path.join(root, f), self._json)

    def _push_image(self):
        try:
            image_name = self._get_image_name()
            info_log(self.TAG, "Squashing and pushing {} to private registry...".format(image_name), app=self.name)
            subprocess.check_call([os.path.join(MainSettings.ROOT, "util", "squash-and-push"), image_name])
        except subprocess.CalledProcessError:
            raise App.BuildFailedException("Could not push {0} to the private registry".format(self.name))

    def _preload_image(self):
        info_log(self.TAG, "Preloading app image onto all nodes...", app=self.name)
        cm = ClusterManager.get_instance().preload_image(self.name)
     
    def build(self, build_base=False, preload=False):
        try:
            # clean up the old build and record the start of a new build
            build_path = os.path.join(self.path, "build")
            make_dir(build_path, clean=True)
            App.index.update_build_state(self, App.BuildState.BUILDING)
            App.index.update_last_build_time(self)

            # fetch the repo
            self._fetch_repo()

            # ensure that the service dependencies are all build
            info_log(self.TAG, "Building service dependencies...", app=self.name)
            for service in self.services:
                built_service = service.build()
                if not built_service:
                    raise App.BuildFailedException("could not build service {}".format(service.full_name))

            # copy new file and replace all template placeholders with parameters
            self._fill_templates(build_path)

            if build_base:
                self._build_base_image()

            app_img_path = os.path.join(build_path, "app")
            make_dir(app_img_path)
            shutil.copytree(self.repo, os.path.join(app_img_path, "repo"))
            if "dockerfile" in self.dependencies:
                self._build_with_dockerfile(build_path)
            else:
                self._build_without_dockerfile(build_path)

            # push the app image to the private registry
            self._push_image()

            # if preload is set, send the app image to all nodes
            if preload:
                self._preload_image()

        except App.BuildFailedException as e:
            App.index.update_build_state(self, App.BuildState.FAILED)
            error_log(self.TAG, str(e), app=self.name)
            return

        info_log(self.TAG, "Successfully built app {0}".format(self.name), app=self.name)
        App.index.update_build_state(self, App.BuildState.COMPLETED)

    def deploy(self, mode):
        # every service must be deployable in single-node mode, so this is valid even if there
        # aren't any services
        if not mode:
            mode = "single-node"

        success = True

        # clean up the old deployment
        deploy_path = os.path.join(self.path, "deploy")
        if os.path.isdir(deploy_path):
            shutil.rmtree(deploy_path)
        os.mkdir(deploy_path)

        services = self.services
        app_params = self.get_app_params()

        # load all the template strings
        templates_path = os.path.join(MainSettings.ROOT, "templates")
        template_names = ["namespace.json", "pod.json", "service-pod.json", "notebook.json",
                          "controller.json", "service.json"]
        templates = {}
        for name in template_names:
            with open(os.path.join(templates_path, name), 'r') as tf:
                templates[name] = tf.read()

        # insert the notebooks container into the pod.json template
        with open(os.path.join(deploy_path, "notebook.json"), 'w+') as nb_file:
            nb_string = fill_template_string(templates["notebook.json"], app_params)
            nb_file.write(nb_string)

        # insert the namespace file into the deployment folder
        with open(os.path.join(deploy_path, "namespace.json"), 'w+') as ns_file:
            ns_string = fill_template_string(templates["namespace.json"], app_params)
            ns_file.write(ns_string)

        # write deployment files for every service (by passing app parameters down to each service)
        for service in services:
            deployed_service = service.deploy(mode, deploy_path, self, templates)
            if not deployed_service:
                success = False

        # use the cluster manager to deploy each file in the deploy/ folder
        redirect_url = ClusterManager.get_instance().deploy_app(self.app_id, deploy_path)
        if not redirect_url:
            success = False

        if success:
            app_id = app_params["app.id"]
            msg = "Successfully deployed app {0} in {1} mode with ID {2}".format(self.name, mode, app_id)
            info_log(self.TAG, msg)
            return redirect_url
        else:
            error_log(self.TAG, "Failed to deploy app {0} in {1} mode.".format(self.name, mode))
            return None

    def destroy(self):
        pass
