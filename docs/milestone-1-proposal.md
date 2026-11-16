# Milestone 1 proposal

Paste-ready draft for Canvas. Milestone 1 is due Friday, November 20, 2026,
11:59 pm CST. The assignment asks for one or two paragraphs covering the
problem, the server-side components, and three non-trivial operations.

---

**GNSS Interference Watch.** GPS jamming and spoofing near conflict zones such as the Baltic and Black Seas disrupt aviation, shipping and weather data, but hotspots are still found mostly by hand. Our project is a serverless AWS service that detects them automatically from public GNSS radio-occultation (RO) satellite data. When GPS signals are jammed, RO satellites collect far fewer atmospheric profiles over the area. In October 2026 the Baltic received only about 0.10–0.14× the expected number of PlanetIQ and Spire profiles, while control regions were near 1.0×. Every day, the service downloads PlanetIQ, Spire and COSMIC-2 profiles published by UCAR, compares regional counts with each provider's baseline, cross-checks flagged regions against GPSJam's aircraft-based interference maps, and alerts subscribers.

**Components:** an EventBridge-scheduled Lambda that fans work out through an SQS queue (with a dead-letter queue) to a container-image ingest Lambda; S3 for Parquet profile extracts; DynamoDB for regions, daily counts, anomalies, jobs and subscriptions; a Step Functions workflow for daily analysis; SNS for email alerts (optional Bedrock summaries); and an API Gateway + Lambda REST API used by a simple Leaflet web-map client. **Three non-trivial operations:** (1) parallel ingest, in which UCAR tarballs are downloaded and decoded (netCDF/BUFR) and each profile is assigned to a region of interest; (2) anomaly detection, which computes density ratios against latitude-band baselines and flags regions with rolling z-scores; and (3) data fusion and alerting, which measures overlap and correlation with GPSJam data, assigns a risk score, and sends alerts. Work is split three ways: Collect, Detect, and Alert & Show.
