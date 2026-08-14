# homelab-k8s

GitOps repo for my homelab Kubernetes cluster (kubeadm, two nodes, Flux). Flux watches
this repo and reconciles the cluster from it — changes happen by editing manifests and
pushing, not by running kubectl against the cluster.

## Layout

`clusters/homelab/` is the Flux entry point: one Kustomization per namespace, prune
enabled. Each namespace directory lists exactly what it applies in its own
`kustomization.yaml`. Helm-managed apps (SonarQube, gitlab-agent,
sops-secrets-operator) are HelmRelease CRs rather than raw manifests.

## Secrets

SOPS-encrypted with age, decrypted in-cluster by sops-secrets-operator. The
`.sops.yaml` files in this repo are ciphertext; the age private key never touches git.
Plain Kubernetes Secrets are never committed.

## Image automation

CI tags each build `main-<timestamp>-<sha>`. Flux's image-reflector scans the
registry, and ImageUpdateAutomation commits the tag bump back to this repo, so a
deploy is just a merge plus one automated commit.

## Odds and ends

- MetalLB (L2) hands out LoadBalancer IPs, Traefik terminates ingress.
- Longhorn backs app config volumes, with scheduled snapshots and backups to NAS
  storage over NFS.
- The `monitoring/` stack (Prometheus, Grafana, Loki, Alertmanager) is currently
  applied manually — moving it under Flux is on the list.

Curated copy of a private repo: fresh history, network addressing rewritten, and some
namespaces not included for privacy. Cluster bootstrap isn't covered here.
