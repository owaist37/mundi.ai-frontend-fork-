---
title: On-Premise/VPC Kubernetes Deployment
description: Mundi can be deployed on-premise or in a virtual private cloud as a Kubernetes cluster with our Helm charts
---

On-prem Mundi is an extension of open source Mundi that's designed for use with frontier LLMs,
multi-user authentication (SSO/SAML), and is highly available to entire teams simultaneously.

The vast majority of our users are best using Mundi cloud, which is our most advanced
and feature-complete offering, or
[open source Mundi](https://github.com/buntinglabs/mundi.ai), which is free, self-hostable, and
open source (AGPLv3). We recommend on-prem Mundi only for large
organizations or organizations with sensitive data requirements.

:::note
Deployment configurations for Mundi change over time. For the most up-to-date
information, [schedule a call](https://cal.com/buntinglabs/30min) with us.
:::

## Deployment configuration

We use a Kubernetes environment provisioned by [Helm charts](https://helm.sh/).

On-prem Mundi can be deployed either as cloud-hosted or self-managed. For
cloud-hosted configurations, the [Bunting Labs team](https://buntinglabs.com/)
can manage the Mundi Kubernetes
cluster in your VPC. This allows us to deploy updates as needed.

An organization's IT team can also self-manage the Kubernetes environment,
working closely with our engineering team to work through any issues in a
privacy-preserving manner. Log access is not required. Self-managed deployments
can be configured to not expose any data to Bunting Labs.

### Compatible cloud providers

We run Mundi cloud on
[Google Kubernetes Engine (GKE)](https://cloud.google.com/kubernetes-engine). However, Mundi should be
compatible with Amazon Web Services (AWS), Microsoft Azure, and other providers
with dedicated Kubernetes support.

### LLM / AI Model Requirements

The user experience in Mundi is better the more powerful of a model Mundi has
access to. The most powerful models are called *frontier models* and represent
the best the AI labs have to offer. Frontier models are closed weights and only
available via API.

For organizations with data privacy requirements, there are two main options:
privacy agreements with LLM providers and self-hosting local LLMs.

**Privacy agreements with LLM providers**: Many AI providers, including OpenAI,
Anthropic, AWS, Microsoft Azure, and Google Gemini will agree to a
*Zero Data Retention* agreement with the right organizations. If your organization
has negotiated an agreement with an LLM provider you want to use with Mundi,
on-prem Mundi is compatible with any Chat Completions-compatible API.
[AWS Bedrock](https://aws.amazon.com/bedrock/) is frequently used.

**Local LLMs**: For organizations that can would prefer the data never leaves
their managed cluster, it is possible to run open-weights models like Google's Gemma,
Meta's Llama, and DeepSeek. This requires GPUs to be added to the deploymenet for
reasonable performance.

## Service-level agreements

SLAs are available for VPC environments we manage, while self-managed deployments
can have a response time SLA.
