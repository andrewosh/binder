## :dash: :dash: **The Binder Project is moving to a [new repo](https://github.com/jupyterhub/binderhub).** :dash: :dash:

:books: Same functionality. Better performance for you. :books:

Over the past few months, we've been improving Binder's architecture and infrastructure. We're retiring this repo as it will no longer be actively developed. Future development will occur under the [JupyterHub](https://github.com/jupyterhub/) organization.

* All development of the Binder technology will occur in the [binderhub repo](https://github.com/jupyterhub/binderhub)
* Documentation for *users* will occur in the [jupyterhub binder repo](https://github.com/jupyterhub/binder) 
* All conversations and chat for users will occur in the [jupyterhub binder gitter channel](https://gitter.im/jupyterhub/binder)

Thanks for updating your bookmarked links.

## :dash: :dash: **The Binder Project is moving to a [new repo](https://github.com/jupyterhub/binderhub).** :dash: :dash:

---

# binder

> reproducible executable environments

[![chatroom](https://img.shields.io/gitter/room/binder-project/binder.svg?style=flat-square)](https://gitter.im/binder-project/binder)

Binder is a collection of tools for building and executing version-controlled computational environments that contain code, data, and interactive front ends, like [Jupyter](http://jupyter.org) notebooks. It's 100% open source. We maintain a small cluster for public use, but it's also easy to deploy the system yourself. 

This repository does not contain any actual code, but serves as a reference for Binder information, and a place to post issues or questions about the project. All Binder components are written in `node.js` but an earlier version written in `python` can be found on the [`legacy`](https://github.com/binder-project/binder/tree/legacy) branch of this repository.

See [`mybinder.readthedocs.io`](http://mybinder.readthedocs.io) for official documentation.

### concept

At a high level, Binder is designed to make the following workflow as easy as possible

- Users specify a GitHub repository
- Repository contents are used to build [Docker](http://docker.com) images
- Deploy containers on-demand in the browser on a cluster running [Kubernetes](http://kubernetes.io)

Common use cases include:
- sharing scientific work
- sharing journalism
- running tutorials and demos with minimal setup
- teaching courses

### components

Binder is implemented through a collection of NodeJS modules, each of which can be independently tested and versioned. The key components are:

- [`binder-build`](https://github.com/binder-project/binder-build) build Docker images from repository contents
- [`binder-deploy-kubernetes`](https://github.com/binder-project/binder-deploy-kubernetes) deploy images on a Kubernetes cluster
- [`binder-control`](https://github.com/binder-project/binder-control) CLI for setting up binder components for a deployment
- [`binder-client`](https://github.com/binder-project/binder-client) CLI and library for interacting with a binder deployment
- [`binder-web`](https://github.com/binder-project/binder-web) web frontend for a Binder deployment

### for users

We maintain a public Binder cluster at [`mybinder.org`](http://mybinder.org) running on Google Compute Engine, supported by [HHMI Janelia Research Center](https://janelia.org), and designed for open source and open science projects. You just need to specify a GitHub repository, and you'll get a badge to embed in your project README that launches the environment. Head to [`mybinder.org`](http://mybinder.org) to try it out.

### for developers

We've also made it easy to setup a custom Binder deployment on your own compute infrastructure. This is a great idea if you need guarenteed availability (e.g. for a course), want to use an existing compute cluster, or need access to private data. It's also a great way to understand the system and start contributing new features! See the `devs` section of [`docs.mybinder.org`](http://docs.mybinder.org) to get started.

### contributing

We welcome community contributions! You can submit issues or pull requests to the repository for the component you're interested in working on, e.g. if you have an idea for improving how dependencies are resolved, open an issue on [`binder-build`](https://github.com/binder-project/binder-build). But if you're unsure, you can just open an issue on this repository.

