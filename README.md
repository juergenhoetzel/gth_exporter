GoveeLife Bluetooth Thermometer Hygrometer Exporter
====================================================

# Export targets

  * JSON
  * [Grafana Graphite metrics](https://grafana.com/docs/grafana-cloud/send-data/metrics/metrics-graphite/)


# Tested Devices

  * H5105

# Example Usage

```bash
gth_exporter -l DEBUG -a CE:39:33:30:33:05=living_room -a D8:35:33:33:6A:5C=kitchen -t 60 -g "https://graphite-prod-13-prod-us-east-0.grafana.net/graphite/metrics"  -b hci1
```




