- https://knative.dev/docs/install/knative-with-operators/

- https://istio.io/latest/docs/setup/install/istioctl/
    - `brew install istioctl`

```
rch:~ rch$ istioctl install
This will install the default Istio profile into the cluster. Proceed? (y/N) y
Detected that your cluster does not support third party JWT authentication. Falling back to less secure first party JWT. See https://istio.io/docs/ops/best-practices/security/#configure-third-party-service-account-tokens for details.
✔ Istio core installed
✔ Istiod installed
✔ Ingress gateways installed
✔ Installation complete
```

> In general, you can use the --set flag in istioctl as you would with Helm. The only difference is you must prefix the setting paths with values. because this is the path to the Helm pass-through API in the IstioOperator API.

```
rch:~ rch$ kubectl -n istio-system get deploy
NAME                   READY   UP-TO-DATE   AVAILABLE   AGE
istio-ingressgateway   1/1     1            1           3m52s
istiod                 1/1     1            1           4m22s
```

- https://knative.dev/development/install/installing-istio/

> The current known-to-be-stable version of Istio tested in conjunction with Knative is v1.4.10. Versions in the 1.4 line generally be fine too. Versions above the 1.4 line are under test but have not stabilized yet.


```
rch:~ rch$ istioctl version
client version: 1.7.3
control plane version: 1.7.3
data plane version: 1.7.3 (1 proxies)
```

# Installing Istio without sidecar injection
> Enter the following command to install Istio:

```
rch:docs rch$ istioctl manifest apply -f istio-minimal-operator.yaml
Error: unknown shorthand flag: 'f' in -f
```

> ...

```
rch:docs rch$ istioctl install -f istio-minimal-operator.yaml
Detected that your cluster does not support third party JWT authentication. Falling back to less secure first party JWT. See https://istio.io/docs/ops/best-practices/security/#configure-third-party-service-account-tokens for details.
✔ Istio core installed
✔ Istiod installed
✔ Addons installed
✔ Ingress gateways installed
✔ Installation complete
```

# Installing Istio with sidecar injection
> If you want to enable the Istio service mesh, you must enable automatic sidecar injection. The Istio service mesh provides a few benefits...

```
# To automatic sidecar injection, set autoInject: enabled in addition to above operator configuration.

    global:
      proxy:
        autoInject: enabled
```

- Enable sidecar container on `knative-serving` system namespace.

```
rch:docs rch$ kubectl label namespace knative-serving istio-injection=enabled
Error from server (NotFound): namespaces "knative-serving" not found
```

- https://knative.dev/docs/install/knative-with-operators/
- Install the latest Knative operator with the following command:

```
kubectl apply -f https://github.com/knative/operator/releases/download/v0.18.0/operator.yaml
```

```
rch:docs rch$ kubectl apply -f https://github.com/knative/operator/releases/download/v0.18.0/operator.yaml
error: unable to read URL "https://github.com/knative/operator/releases/download/v0.18.0/operator.yaml", server reported 404 Not Found, status code=404
```

> ...

```
rch:docs rch$ kubectl apply -f https://github.com/knative/operator/releases/download/v0.17.0/operator.yaml
customresourcedefinition.apiextensions.k8s.io/knativeeventings.operator.knative.dev created
customresourcedefinition.apiextensions.k8s.io/knativeservings.operator.knative.dev created
configmap/config-logging created
configmap/config-observability created
deployment.apps/knative-operator created
clusterrole.rbac.authorization.k8s.io/knative-serving-operator-aggregated created
clusterrole.rbac.authorization.k8s.io/knative-serving-operator created
clusterrole.rbac.authorization.k8s.io/knative-eventing-operator-aggregated created
clusterrole.rbac.authorization.k8s.io/knative-eventing-operator created
clusterrolebinding.rbac.authorization.k8s.io/knative-serving-operator created
clusterrolebinding.rbac.authorization.k8s.io/knative-serving-operator-aggregated created
clusterrolebinding.rbac.authorization.k8s.io/knative-eventing-operator created
clusterrolebinding.rbac.authorization.k8s.io/knative-eventing-operator-aggregated created
serviceaccount/knative-operator created
```

# Verify the operator installation

```
rch:docs rch$ kubectl get deployment knative-operator
NAME               READY   UP-TO-DATE   AVAILABLE   AGE
knative-operator   1/1     1            1           1m27s

rch:docs rch$ kubectl logs -f deploy/knative-operator
2020/10/05 20:12:59 maxprocs: Leaving GOMAXPROCS=4: CPU quota undefined
2020/10/05 20:12:59 Registering 2 clients
2020/10/05 20:12:59 Registering 3 informer factories
2020/10/05 20:12:59 Registering 3 informers
2020/10/05 20:12:59 Registering 2 controllers
{"level":"info","ts":"2020-10-05T20:12:59.413Z","caller":"logging/config.go:110","msg":"Successfully created the logger."}
{"level":"info","ts":"2020-10-05T20:12:59.413Z","caller":"logging/config.go:111","msg":"Logging level set to info"}
{"level":"info","ts":"2020-10-05T20:12:59.413Z","caller":"logging/config.go:78","msg":"Fetch GitHub commit ID from kodata failed","error":"open /var/run/ko/HEAD: no such file or directory"}
{"level":"info","ts":"2020-10-05T20:12:59.413Z","logger":"knative-operator","caller":"profiling/server.go:59","msg":"Profiling enabled: false"}
{"level":"info","ts":"2020-10-05T20:12:59.417Z","logger":"knative-operator","caller":"leaderelection/context.go:46","msg":"Running with Standard leader election"}
...
...
```

- Create and apply the Knative Serving CR:
    - You can install the latest available Knative Serving in the operator by applying a YAML file containing the following:
```
apiVersion: v1
kind: Namespace
metadata:
 name: knative-serving
---
apiVersion: operator.knative.dev/v1alpha1
kind: KnativeServing
metadata:
  name: knative-serving
  namespace: knative-serving
```

```
rch:config rch$ kubectl apply -f knative-serving.yaml
Error from server (NotFound): error when creating "knative-serving.yaml": namespaces "knative-serving" not found

rch:config rch$ kubectl create namespace knative-serving
namespace/knative-serving created

rch:config rch$ kubectl apply -f knative-serving.yaml
knativeserving.operator.knative.dev/knative-serving created
```

```
rch:config rch$ kubectl get deployment -n knative-serving
NAME               READY   UP-TO-DATE   AVAILABLE   AGE
activator          1/1     1            1           14m
autoscaler         1/1     1            1           14m
autoscaler-hpa     1/1     1            1           14m
controller         1/1     1            1           14m
istio-webhook      1/1     1            1           14m
networking-istio   1/1     1            1           14m
webhook            1/1     1            1           14m

rch:config rch$ kubectl get KnativeServing knative-serving -n knative-serving
NAME              VERSION   READY   REASON
knative-serving   0.17.1    True
```

- https://knative.dev/docs/install/knative-with-operators/#installing-the-knative-eventing-component
- https://knative.dev/docs/install/knative-with-operators/#uninstall-knative

# Set up Elixir and Phoenix Locally

- https://knative.dev/community/samples/serving/helloworld-elixir/
    - Generate a new project. e.g. `mix phoenix.new $APP_NAME`
    - In the new directory, create a new `Dockerfile` for packaging your application for deployment
    - Create a `service.yaml` file containing the Service definition.
    - Build the container on your local machine:


```
rch:gaius rch$ DOCKER_USER=zndx

rch:gaius rch$ APP_NAME=gaius

rch:gaius rch$ mix phx.new --no-ecto $APP_NAME
...
rch:gaius rch$ SECRET_KEY_BASE=$(mix phx.gen.secret)

# replace {username} in `service.yaml` 
# add SECRET_KEY_BASE to Dockerfile

rch:gaius rch$ docker build -t $DOCKER_USER/helloworld-elixir .

# mix deps.clean gettext

rch:gaius rch$ docker build -t $DOCKER_USER/helloworld-elixir .

** (Mix) Could not compile dependency :cowboy, "/root/.mix/rebar3 bare compile --paths "/opt/app/_build/prod/lib/*/ebin"" command failed. You can recompile this dependency with "mix deps.compile cowboy", update it with "mix deps.update cowboy" or clean it with "mix deps.clean cowboy"

rch:gaius rch$ mix deps.clean cowboy

rch:gaius rch$ mix deps.update cowboy

rch:gaius rch$ docker build -t $DOCKER_USER/helloworld-elixir .
```

# FAIL

```
rch:gaius rch$ brew info elixir

elixir: stable 1.10.4 (bottled), HEAD
Functional metaprogramming aware language built on Erlang VM
https://elixir-lang.org/
/usr/local/Cellar/elixir/1.10.4 (430 files, 5.9MB) *
  Poured from bottle on 2020-08-12 at 17:56:24
From: https://github.com/Homebrew/homebrew-core/blob/HEAD/Formula/elixir.rb
License: Apache-2.0
==> Dependencies
Required: erlang ✘
...

rch:gaius rch$ brew reinstall elixir
rch:gaius rch$ mix deps.get
rch:gaius rch$ iex -S mix phx.server
```

```
rch:gaius rch$ mix deps
* cowboy (Hex package) (rebar3)
  locked at 2.8.0 (cowboy) 4643e4fb
  the dependency is not available, run "mix deps.get"

rch:gaius rch$ mix deps.get
...
* Getting gettext (Hex package)
* Getting cowboy (Hex package)

# downgrade cowboy
# mess with plug
```

- update `Dockerfile` to use `elixer:1.10.4-alpine`

- `cd assets && npm i brunch`

```
Step 11/22 : RUN mix release --env=prod --verbose     && mv _build/prod/rel/${APP_NAME} /opt/release     && mv /opt/release/bin/${APP_NAME} /opt/release/bin/start_server
 ---> Running in 1c4155570b38
** (Mix) Could not invoke task "release": 2 errors found!
--env : Unknown option
--verbose : Unknown option
```

















