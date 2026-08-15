# Kubernetes Scaffolding

These manifests describe the current frontend, API, migration, and RQ worker processes. They are local deployment scaffolding only and have not been deployed to or validated against a production cluster.

PostgreSQL, Redis, and S3-compatible object storage are external dependencies. Before applying the manifests:

1. Set `S3_BUCKET_NAME`, region, endpoint, and path-style behavior in `configmap.yaml` for the target provider.
2. Copy `secret.example.yaml` to the ignored `secret.yaml` file and replace every required placeholder.
3. Replace the local image names in the Deployments and Job with images available to the target cluster, or load locally built images into a local cluster.

```powershell
Copy-Item deploy/kubernetes/secret.example.yaml deploy/kubernetes/secret.yaml
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/secret.yaml
kubectl apply -k deploy/kubernetes
```

No ingress, domain, certificate, cloud database, broker, or object store is created. For local access after applying to a configured cluster:

```powershell
kubectl port-forward -n document-intelligence service/document-intelligence-frontend 3000:80
```

The migration Job runs `alembic upgrade head` separately. API replicas disable entrypoint migrations, and the standalone worker uses the existing Redis/RQ transport with PostgreSQL remaining authoritative for job state.
