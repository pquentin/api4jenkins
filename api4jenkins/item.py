# encoding: utf-8

import logging
import re
from importlib import import_module

from requests.exceptions import HTTPError

from .exceptions import (AuthenticationError, BadRequestError,
                         ItemNotFoundError, ServerError, UnsafeCharacterError)

logger = logging.getLogger(__name__)


def camel(s):
    if s[0] == '_':
        return s
    first, *other = s.split('_')
    return first.lower() + ''.join(x.title() for x in other)


def _snake():
    pattern = re.compile(r'(?<!^)(?=[A-Z])')

    def func(name):
        return pattern.sub('_', name).lower()
    return func


snake = _snake()


def append_slash(url):
    return url if url[-1] == '/' else url + '/'


def _new_item():
    delimiter = re.compile(r'[.$]')
    def func(jenkins, module, item):
        logger.debug(item)
        class_name = delimiter.split(item['_class'])[-1]
        module = import_module(module)
        if not hasattr(module, class_name):
            raise AttributeError(f'{module} has no class {class_name}, '
                                    'Patch new class with'
                                    ' api4jenkins._patch_to')
        _class = getattr(module, class_name)
        return _class(jenkins, item['url'])
    return func

new_item = _new_item()

class Item:
    '''
    classdocs
    '''
    headers = {'Content-Type': 'text/xml; charset=utf-8'}
    class_delimiter = re.compile(r'[.$]')

    _attrs = []

    def __init__(self, jenkins, url):
        self.jenkins = jenkins
        self.url = append_slash(url)

    def api_json(self, tree='', depth=0):
        params = {'depth': depth}
        if tree:
            params['tree'] = tree
        return self.handle_req('GET', 'api/json', params=params).json()

    def handle_req(self, method, entry, **kwargs):
        self._add_crumb(kwargs)
        try:
            return self.jenkins.send_req(method, self.url + entry, **kwargs)
        except HTTPError as e:
            if e.response.status_code == 404:
                raise ItemNotFoundError('No such item: %s' % self) from e
            elif e.response.status_code == 401:
                raise AuthenticationError(
                    'Invalid authorization for %s' % self) from e
            elif e.response.status_code == 403:
                raise PermissionError(
                    'No permission to %s for %s' % (entry, self.url)) from e
            elif e.response.status_code == 400:
                raise BadRequestError(e.response.headers['X-Error']) from e
            elif e.response.status_code == 500:
                #                 import xml.etree.ElementTree as ET
                #                 tree = ET.fromstring(e.response.text)
                #                 stack_trace = tree.find(
                #                     './/div[@id="error-description"]/pre').text

                raise ServerError(e.response.text) from e
            raise

    def _add_crumb(self, kwargs):
        if self.jenkins.crumb:
            headers = kwargs.get('headers', {})
            _crumb = {self.jenkins.crumb['crumbRequestField']: self.jenkins.crumb['crumb']}
            headers.update(_crumb)
            kwargs['headers'] = headers

    def _new_instance_by_item(self, module, item):
        logger.debug(item)
        class_name = self.class_delimiter.split(item['_class'])[-1]
        module = import_module(module)
        if not hasattr(module, class_name):
            raise AttributeError(f'{module} has no class {class_name}, '
                                 'Patch new class with'
                                 ' api4jenkins._patch_to')
        _class = getattr(module, class_name)
        return _class(self.jenkins, item['url'])

    def exists(self):
        try:
            self.api_json(tree='_class')
            return True
        except ItemNotFoundError:
            return False

    @property
    def attrs(self):
        if not self._attrs:
            data = self.api_json()
            self.__class__._attrs = \
                [snake(attr) for attr in data if isinstance(
                    data[attr], (int, str, bool, type(None)))]
        return self._attrs

    def __eq__(self, other):
        return type(self) == type(other) and self.url == other.url

    def __str__(self):
        return f'<{type(self).__name__}: {self.url}>'

    def __getattr__(self, name):
        if name in self.attrs:
            attr = camel(name)
            return self.api_json(tree=attr)[attr]
        return super().__getattribute__(name)
