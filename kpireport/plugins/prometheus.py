from datetime import timedelta
from itertools import chain
from functools import lru_cache, reduce
from operator import itemgetter
import pandas as pd
import re
import requests

from kpireport.datasource import Datasource
from kpireport.view import View


class PrometheusDatasource(Datasource):
    """Datasource that executes PromQL queries against a Prometheus server.

    :type host: str
    :param host: the hostname of the Prometheus server (may include port),
                 e.g., :samp:`https://prometheus.example.com:9090`
    """
    def init(self, host=None):
        if not host:
            raise ValueError("Missing required parameter: 'host'")
        if not host.startswith("http"):
            host = f"http://{host}"
        self.host = host

    def query(self, query: str, step="1h") -> pd.DataFrame:
        """Execute a PromQL query against the Prometheus server.

        :type query: str
        :param query: the PromQL query
        :type step: str
        :param step: the step size for the range query. The Datasource will
                     execute a `range query <https://prometheus.io/docs/prometheus/latest/querying/api/#range-queries>`_
                     over the report window and capture all time series data
                     within the report boundaries. The step size indicates the
                     query resolution. A lower value provides more granularity
                     but at the cost of a more expensive query and more data
                     points to analyze. If your report window is significantly
                     short, it may make sense to reduce this.
        :rtype: pandas.DataFrame
        :returns: a table of time series results. The timeseries value will
                  be in a ``time`` column; any labels associated with the
                  metric will be added as additional columns.
        """
        res = requests.get(f"{self.host}/api/v1/query_range", params=dict(
            start=self.report.start_date.timestamp(),
            end=self.report.end_date.timestamp(),
            step=step,
            query=query.strip()
        ))
        json = res.json()

        if json.get("status") != "success":
            raise ValueError("Got error response from Prometheus server")

        result = json.get("data", {}).get("result", [])

        df = pd.DataFrame()

        for metric in result:
            mdf = pd.DataFrame(metric["values"], columns=["time", "value"])
            mdf["time"] = pd.to_datetime(mdf["time"], unit="s")
            mdf = mdf.assign(**metric["metric"])
            mdf = mdf.astype({"value": "float"})
            df = df.append(mdf)

        return df


class PrometheusAlertSummary(View):
    """Display a list of alerts that fired recently.

    Supported output formats: ``html``, ``md``, ``slack``

    :type datasource: str
    :param datasource: the ID of the Prometheus Datasource to query
    :type resolution: str
    :param resolution: the size of the time window used to group alerts--the
                       window is used to define buckets. A higher resolution
                       is a lower time window (e.g., "5m" versus "1h"--"5m"
                       is the higher resolution). Higher resolutions mean the
                       timeline and time estimates for outage length will be
                       more accurate, but may decrease performance when the
                       report interval is large, as it requires pulling more
                       data from Prometheus. (default=15m)
    :type ignore_labels: List[str]
    :param ignore_labels: a set of labels to hide from the output display.
                          Alerts containing these labels will still be listed,
                          but the label values will not be printed.
                          (default=["instance", "job"])
    :type labels: Dict[str,str]
    :param labels: a set of labels that the alert must contain in order to
                   be displayed (default=None)
    :type show_timeline: bool
    :param show_timeline: whether to show a visual timeline of when alerts
                          were firing (default=True)
    """
    RESOLUTION_REGEX = r"([0-9]+)([smhdwy])"

    def init(self, datasource="prometheus", resolution="15m",
             ignore_labels=["instance", "job"],
             labels=None, show_timeline=True):
        self.datasource = datasource
        self.resolution = self._parse_resolution(resolution)
        self.ignore_labels = ignore_labels
        self.labels = labels
        self.show_timeline = show_timeline

    def _parse_resolution(self, res):
        match = re.match(self.RESOLUTION_REGEX, res)

        if not match:
            raise ValueError("Invalid resolution format")

        mapping = {
            "s": "seconds",
            "m": "minutes",
            "h": "hours",
            "d": "days",
            "w": "weeks",
            "y": "years",
        }

        timedelta_kwargs = {mapping[match.group(2)]: int(match.group(1))}
        return timedelta(**timedelta_kwargs)

    def _compute_time_windows(self, df_ts):
        list_ts = df_ts.tolist()
        if not list_ts:
            return []

        windows = [[list_ts[0], list_ts[0] + self.resolution]]
        for ts in list_ts:
            if ts > windows[-1][1]:
                # If we have over-run the last window, start a new one.
                windows.append([ts, ts + self.resolution])
            else:
                # Expand last window to include time.
                windows[-1][1] = ts + self.resolution

        return windows

    def _compress_time_windows(self, windows):
        sorted_windows = sorted(windows, key=itemgetter(0))
        compressed = sorted_windows[:1]
        for start, end in sorted_windows[1:]:
            if start < compressed[-1][1]:
                compressed[-1][1] = max(compressed[-1][1], end)
            else:
                compressed.append([start, end])
        return compressed

    def _total_time(self, windows):
        return reduce(lambda agg, x: agg + (x[1] - x[0]),
                      windows, timedelta(0))

    def _normalize_time_windows(self, windows):
        """Normalize time windows to a single [0,100] scale."""
        td = self.report.timedelta
        return [
            (max(0, (round(100 * (w[0] - self.report.start_date) / td, 2))),
             round(100 * (w[1] - w[0]) / td, 2))
            for w in windows
        ]

    @lru_cache(maxsize=1)
    def _template_vars(self):
        df = self.datasources.query(
            self.datasource, "ALERTS", step=self.resolution.total_seconds())

        # Filter out pending alerts that never fired
        df = df[df["alertstate"] == "firing"]

        if self.labels:
            for key, value in self.labels.items():
                df = df[df[key] == value]

        ignore_labels = ["__name__", "alertstate"] + self.ignore_labels
        df = df.drop(labels=ignore_labels, axis="columns", errors="ignore")

        summary = []
        for alertname in df["alertname"].unique():
            df_a = df[df["alertname"] == alertname]
            df_a = df_a.drop(labels="alertname", axis="columns")

            # Drop label columns that were not used for this alert
            df_a = df_a.dropna(how="all", axis="columns")

            # Round data points to resolution steps
            offset = pd.tseries.frequencies.to_offset(self.resolution)
            df_a["time"] = df_a["time"].dt.round(offset)

            # Find common label sets and which times those alerts fired
            labels = list(df_a.columns[2:])
            df_ag = df_a.groupby(labels)["time"]
            firings = [
                dict(
                    labels=dict(zip(labels, labelvalues)),
                    windows=self._compute_time_windows(df_times)
                )
                for labelvalues, df_times in df_ag
            ]

            # Find times during which any alert of this type fired
            all_firings = list(chain(*[f["windows"] for f in firings]))
            windows = self._compress_time_windows(all_firings)
            total_time = self._total_time(windows)

            summary.append(dict(
                alertname=alertname,
                total_time=total_time,
                num_firings=len(all_firings),
                windows=windows,
            ))

        time_ordered = sorted(summary, key=itemgetter("total_time"),
                              reverse=True)
        timeline = self._normalize_time_windows(
            list(chain(*[a["windows"] for a in summary])))

        return dict(
            summary=time_ordered,
            timeline=timeline,
            show_timeline=self.show_timeline
        )

    def _render(self, j2, fmt):
        template = j2.get_template(f"plugins/prometheus_alert_summary.{fmt}")
        return template.render(**self._template_vars())

    def render_html(self, j2):
        return self._render(j2, "html")

    def render_md(self, j2):
        return self._render(j2, "md")

    def render_slack(self, j2):
        return self._render(j2, "slack")
