# Adaptive GIS Traffic Shaping

A research-inspired adaptive traffic-shaping prototype for evaluating rate control under concurrent workloads using a Hidden Markov Model (HMM), an adaptive rate controller, and the Token Bucket algorithm.

**Live Demo:** [Open the application](https://adaptive-token-bucket.vercel.app/)  
**Backend API:** [FastAPI Service](https://adaptive-gis-traffic-shaping-api.onrender.com/)  
**API Documentation:** [Swagger UI](https://adaptive-gis-traffic-shaping-api.onrender.com/docs)

---

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Project Objectives](#project-objectives)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Algorithm Design](#algorithm-design)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Using the Dashboard](#using-the-dashboard)
- [API Reference](#api-reference)
- [Benchmarking Methodology](#benchmarking-methodology)
- [Observed Benchmark Results](#observed-benchmark-results)
- [Deployment](#deployment)
- [Limitations](#limitations)
- [Future Improvements](#future-improvements)
- [Research Context](#research-context)
- [Author](#author)

---

## Overview

Adaptive GIS Traffic Shaping is a research-oriented software prototype designed to explore how adaptive rate control can influence task processing under varying workloads.

The project implements a classical Token Bucket baseline and an adaptive traffic-shaping approach incorporating a Hidden Markov Model (HMM) and an adaptive rate controller. A FastAPI backend executes configurable benchmark experiments, while a React dashboard presents trial summaries, performance measurements, and downloadable CSV reports.

The application allows users to configure workload scenarios, select the number of requests and repetitions, compare algorithms, and examine the resulting latency and throughput measurements.

The project combines algorithm implementation, concurrent task processing, backend API development, performance benchmarking, frontend visualization, and cloud deployment.

> **Project status:** Research prototype. The application simulates task-processing workloads and evaluates traffic-shaping behavior. It does not currently connect to a live GIS service.

## Problem Statement

Concurrent applications may receive workloads that vary in complexity and arrival rate. A fixed-rate traffic-shaping mechanism can limit incoming work, but it does not dynamically adjust its behavior based on changing workload conditions.

An adaptive controller offers a way to explore how rate adjustments based on estimated workload conditions affect task latency, throughput, and queue waiting time.

This project investigates the behavior of classical and adaptive rate-control approaches through controlled, repeatable benchmark runs.

The goal is to measure and compare their behavior rather than assume that the adaptive approach is always faster or more efficient.

## Project Objectives

- Implement a classical Token Bucket traffic-shaping baseline.
- Integrate an HMM-driven adaptive rate-control prototype.
- Support concurrent processing of configurable synthetic workloads.
- Compare classical and adaptive approaches under identical benchmark configurations.
- Measure average latency, throughput, elapsed time, and queue waiting time.
- Expose experiment execution through REST API endpoints.
- Build an interactive dashboard for configuring experiments and inspecting results.
- Deploy the frontend and backend for public demonstration.

## Key Features

### 1. Configurable Experiments

Configure experiments through the dashboard without modifying source code.

Available workload scenarios:

| Scenario | Description |
|---|---|
| `simple` | Lightweight task-processing workload |
| `general` | Medium-duration task-processing workload |
| `complex` | Longer task-processing workload |
| `mixed` | Combination of task types with different processing durations |
| `dynamic` | Workload with varying task-arrival delays |

The backend accepts concurrency values from 1 to 200 and repetition counts from 1 to 20.

### 2. Classical vs. Adaptive Comparison

Compare the fixed-rate Token Bucket baseline against the adaptive rate controller.

Supported comparison modes:

- `both` — execute both approaches.
- `classical` — execute only the classical baseline.
- `adaptive` — execute only the adaptive approach.

### 3. Performance Metrics

The benchmark records and summarizes measurements including:

- **Average latency:** Time taken by a task from submission to completion, including relevant waiting time.
- **Throughput:** Number of completed tasks per second.
- **Queue waiting time:** Time a task spends waiting after admission and before processing begins.
- **Processing time:** Time spent processing a task.
- **Elapsed time:** Total measured duration of a trial.
- **Completed tasks:** Number of tasks successfully completed in a trial.

These measurements help identify trade-offs between rate control, waiting time, and processing performance.

### 4. Interactive Dashboard

The React dashboard provides:

- Research overview
- Experiment configuration and execution
- Task monitoring
- Algorithm insights
- Project information
- Trial-by-trial comparison charts
- Benchmark summary tables
- CSV downloads for task-level and trial-level
