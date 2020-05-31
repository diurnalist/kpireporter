from functools import lru_cache
import jenkins
import pandas as pd
import re

from kpireport.datasource import Datasource
from kpireport.view import View


class JenkinsDatasource(Datasource):
    """Provides accessors for listing all jobs and builds from a Jenkins host.

    The Jenkins Datasource exposes an RPC-like interface to fetch all jobs,
    as well as job details for each job. The plugin will call the Jenkins API
    at the host specified using a username and API token provided as
    plugin arguments.
    """
    def init(self, host=None, user=None, api_token=None):
        """Initialize the Jenkins Datasource.

        :type host: str
        :param host: the Jenkins host, e.g. https://jenkins.example.com
        :type user: str
        :param user: the Jenkins user to authenticate as
        :type api_token: str
        :param api_token: the Jenkins user API token to authenticate with
        """
        if not host:
            raise ValueError("Missing required paramter: 'host'")
        if not host.startswith("http"):
            host = f"http://{host}"

        self.client = jenkins.Jenkins(host, username=user, password=api_token)

    def query(self, fn_name, *args, **kwargs):
        """Query the Datsource for job or build data.

        Calls a supported accessor function by name and passthrough any
        positional and keyword arguments.

        Examples::

            # Get a list of all jobs in the Jenkins server
            datasources.query("jenkins", "get_all_jobs")
            # Get detailed information about 'some-job'
            datasources.query("jenkins", "get_job_info", "some-job")

        :type fn_name: str
        :param fn_name: the RPC operation to invoke
        :raise ValueError: if an invalid RPC operation is requested
        """
        fn = getattr(self, fn_name, None)
        if not (fn and callable(fn)):
            raise ValueError(f"No such method {fn_name} for Jenkins client")

        return fn(*args, **kwargs)

    def get_all_jobs(self):
        """List all jobs on the Jenkins server

        :returns: a table with columns:

          :fullname: the full job name (will include folder path components)
          :url: a URL that resolves to the job on the Jenkins server

        :rtype: pandas.DataFrame
        """
        jobs = pd.DataFrame.from_records(self.client.get_all_jobs())
        # Filter by jobs that don't have child jobs
        leaf_jobs = jobs[jobs.jobs.isna()]
        return leaf_jobs

    def get_job_info(self, job_name):
        """
        Get a list of builds for a given job, including their statuses.

        :type job_name: str
        :param job_name: the full name of the job
        :returns: a table with the following columns:

            :status: the build status, e.g. "SUCCESS" or "FAILURE"

        :rtype: pandas.DataFrame
        """
        job_info = self.client.get_job_info(job_name, depth=1)
        df = pd.json_normalize(job_info, "builds")
        # Transpose the health report information into our result table--
        # this is a bit of a hack but it avoids having to make two calls
        # to our datasource (DataFrames don't handle mixed dict/list data)
        return df.assign(**job_info["healthReport"])


class JenkinsBuildFilter:
    """Filters a list of Jenkins jobs/builds by a general criteria

    Currently only filtering by name is supported, but this class can be
    extended in the future to filter on other attributes, such as build status
    or health.

    :type name: Union[str, List[str]]
    :param name: the list of name filter patterns. These will be compiled
                    as regular expressions. In the case of a single filter,
                    a string can be provided instead of a list.
    :type invert: bool
    :param invert: whether to invert the filter result
    """
    name_filter = None

    def __init__(self, name=None, invert=False):
        self.invert = invert
        if name:
            self.name_filter = self._process_filters(name)

    def _process_filters(self, filters):
        if not (isinstance(filters, list) or isinstance(filters, str)):
            raise ValueError((
                "Invalid filter type, only string or "
                "list of strings supported"))
        if not isinstance(filters, list):
            filters = [filters]
        return [re.compile(f) for f in filters]

    def filter_job(self, job):
        """Checks a job against the current filters

        :type job: dict
        :param job: the Jenkins job
        :rtype: bool
        :returns: whether the job passes the filters
        """
        allow = True

        if self.name_filter:
            job_name = job["fullname"]
            allow &= all(f.search(job_name) for f in self.name_filter)

        if self.invert:
            allow = not allow

        return allow


class JenkinsBuildSummary(View):
    """Display a list of jobs with their latest build statuses, and health.

    :formats: html, md

    :type datasource: str
    :param datasource: the Datasource ID to query for Jenkins data
    :type filters: dict
    :param filters: optional filters to limit which jobs are rendered in
                    the view. These filters are directly passed to
                    :class:`JenkinsBuildFilter`.
    """
    def init(self, datasource="jenkins", filters={}):
        self.datasource = datasource
        self.filters = JenkinsBuildFilter(**filters)

    @lru_cache
    def _template_vars(self):
        jobs = self.datasources.query(self.datasource, "get_all_jobs")

        summary = []
        for _, row in jobs.iterrows():
            if not self.filters.filter_job(row):
                continue
            job_name = row["fullname"]
            job_url = row["url"]
            builds = self.datasources.query(
                self.datasource, "get_job_info", job_name)
            score = builds["score"].iloc[0]
            # Reverse order of builds, Jenkins returns most recent ones first
            build_list = builds.iloc[::-1].T.to_dict().values()
            summary.append(dict(
                name=job_name,
                url=job_url,
                score=score,
                builds=build_list,
            ))

        return dict(summary=summary)

    def _render(self, j2, fmt):
        template = j2.get_template(f"plugins/jenkins_build_summary.{fmt}")
        return template.render(**self._template_vars())

    def render_html(self, j2):
        return self._render(j2, "html")

    def render_md(self, j2):
        return self._render(j2, "md")

    def render_slack(self, j2):
        return self._render(j2, "slack")
