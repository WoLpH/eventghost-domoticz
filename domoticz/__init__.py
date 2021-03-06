from __future__ import print_function

import abc
import math

import requests
import wx

import eg_base
import panels
import utils
import widgets


if not eg_base.TESTING:
    eg_base.eg.RegisterPlugin(
        name='Domoticz',
        guid='{3417a9ba-cbc9-4869-9f4d-87aaa9f57ac2}',
        author='Rick van Hattem <wolph@wol.ph>',
        version='0.2',
        kind='external',
        canMultiLoad=True,
        description='Adds Domoticz devices to EventGhost',
    )


class DomoticzPlugin(panels.Plugin):
    name = 'Domoticz'

    def __init__(self, *args, **kwargs):
        panels.Plugin.__init__(self, *args, **kwargs)
        self.AddAction(DomoticzRaw)
        self.AddAction(DomoticzSwitch)
        self.AddAction(DomoticzBlinds)
        self.AddAction(DomoticzDimmer)

    def __start__(self, config=None):
        panels.Plugin.__start__(self, config)
        self.config.update(config or {})

    @property
    def url(self):
        url = self.config['host'].rstrip('/') + '/json.htm'
        if not url.startswith('http'):
            url = 'http://' + url
        return url

    def GetLabel(self, config, *args, **kwargs):
        return 'Domoticz %s' % config.get('host')

    def Configure(self, config=None, *args):
        panel, config = panels.Plugin.Configure(self, config, *args)
        config.setdefault('timeout', 1)
        config.setdefault('host', 'http://domoticz')

        self.add_field('host')
        self.add_field('user')
        self.add_field('pass', style=wx.TE_PASSWORD)
        self.add_field('timeout', widget=wx.SpinCtrl)
        self.add_label('debug')
        self.add('debug', widget=wx.CheckBox(panel), col=1)
        self.widgets['debug'].SetValue(config.get('debug', False))

        while panel.Affirmed():
            for k, v in self.widgets.items():
                if isinstance(v, wx.TextCtrl):
                    config[k] = v.GetValue().strip()
                elif isinstance(v, wx.CheckBox):
                    if v.Is3State():
                        config[k] = v.Get3StateValue()
                    else:
                        config[k] = v.GetValue()

            try:
                self.getswitches()
                panel.SetResult(config)
                print('Connected to %r' % self.url)
            except Exception as e:
                utils.error('Unable to connect: %r' % e)

    def execute(self, verbose=False, **params):
        config = self.config

        if config.get('user'):
            auth = config.get('user', ''), config.get('pass', '')
        else:
            auth = None

        if verbose or config.get('debug'):
            print(self.url, params)

        timeout = int(config.get('timeout', 1))
        response = requests.get(self.url, auth=auth, params=params,
                                timeout=timeout)
        data = response.json()
        assert data['status'] == 'OK'
        return data

    def getswitches(self, **kwargs):
        data = self.execute(
            type='devices',
            filter='light',
            used='true',
            **kwargs)['result']

        return dict((x['idx'], x) for x in data)


class DomoticzDevice(panels.Action):
    description = 'Sets a domoticz device to a given state'
    columns = (
        ('IDX', 'idx'),
        ('Name', ''),
        ('Status', ''),
        ('Last update', 'LastUpdate'),
    )

    @abc.abstractproperty
    def name(self):
        raise NotImplementedError()

    def GetLabel(self, config, *args, **kwargs):
        return 'Set %s to %s' % (
            config['switch']['Name'],
            config['value'],
        )

    def __call__(self, config, switchcmd, **kwargs):
        self.plugin.execute(
            type='command',
            param='switchlight',
            idx=config['idx'],
            switchcmd=switchcmd,
            verbose=True,
            **kwargs)

    def getswitches(self):
        data = dict()
        switch_type = getattr(self, 'switch_type', self.name)
        for key, value in self.plugin.getswitches().items():
            if value['SwitchType'] == switch_type or not switch_type:
                data[int(key)] = value
        return data

    def Configure(self, config=None, *args):
        panel, config = panels.Action.Configure(self, config, *args)

        switches = self.getswitches()

        if eg_base.TESTING:
            # TODO: make wx somehow automatically resize this widget with the
            # window
            size = 800, 500
        else:
            size = 500, -1

        self.add('switch', widgets.ListCtrl(
            panel, self.columns, switches, selected=config.get('idx'),
            style=wx.LC_SINGLE_SEL, size=size))

        return panel, config, switches

    def affirm(self, panel, switches):
        config = self.config
        while panel.Affirmed():
            value = self.widgets['value'].GetValue()
            switch_list = self.widgets['switch']

            selected = switch_list.GetFirstSelected()
            if selected != -1 and value is not None and value != '':
                idx = switch_list.GetItemData(selected)

                config['idx'] = idx
                config['value'] = value
                config['switch'] = switches[idx]
                panel.SetResult(config)
            else:
                idx = None

            switch_list.setData(self.getswitches(), idx)


class DomoticzRaw(DomoticzDevice):
    name = 'Raw'
    switch_type = None
    columns = DomoticzDevice.columns + (
        ('Type', 'SwitchType'),
    )

    def __call__(self, config):
        DomoticzDevice.__call__(
            self,
            config,
            switchcmd=config['value'],
        )

    def Configure(self, config=None, *args):
        panel, config, switches = DomoticzDevice.Configure(
            self, config, *args)
        self.add_field('value')
        self.affirm(panel, switches)


class DomoticzSwitch(DomoticzDevice):
    name = 'On/Off'

    def __call__(self, config):
        DomoticzDevice.__call__(
            self,
            config,
            switchcmd=config['value'],
        )

    def Configure(self, config=None, *args):
        panel, config, switches = DomoticzDevice.Configure(
            self, config, *args)
        self.add_field('value', widget=wx.ComboBox,
                       choices=('On', 'Off', 'Toggle'))
        self.affirm(panel, switches)


class DomoticzDimmer(DomoticzDevice):
    name = 'Dimmer'

    def __call__(self, config):
        switch = config['switch']
        value = config['value']
        max_level = switch['MaxDimLevel']

        level = min(max_level, math.ceil(value * (max_level / 100.)))
        self.debug('Value %r recalculated to level %r using max: %r',
                   value, level, max_level)

        DomoticzDevice.__call__(
            self,
            config,
            switchcmd='Set Level',
            level=level,
        )

    def Configure(self, config=None, *args):
        panel, config, switches = DomoticzDevice.Configure(
            self, config, *args)
        self.add_field('value', widget=wx.SpinCtrl)
        self.affirm(panel, switches)


class DomoticzBlinds(DomoticzDevice):
    name = 'Blinds'
    switch_type = 'Blinds Percentage'

    def Configure(self, config=None, *args):
        panel, config, switches = DomoticzDevice.Configure(
            self, config, *args)
        self.add_field('value', widget=wx.ComboBox, choices=('Open', 'Close'))
        self.affirm(panel, switches)


if __name__ == '__main__':
    app = wx.App()
    plugin = DomoticzPlugin(config=dict(host='http://domoticz'))
    plugin.Configure()
