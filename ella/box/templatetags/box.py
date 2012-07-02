import logging

from django import template
from django.db import models
from django.utils.encoding import smart_str

from ella.core.cache.utils import get_cached_object
from ella.box.box import Box


log = logging.getLogger('ella.core.templatetags')
register = template.Library()

class ObjectNotFoundOrInvalid(Exception): pass

class EmptyNode(template.Node):
    def render(self, context):
        return u''

class BoxNode(template.Node):

    def __init__(self, box_type, nodelist, model=None, lookup=None, var=None):
        self.box_type, self.nodelist, self.var, self.lookup, self.model = box_type, nodelist, var, lookup, model

    def get_obj(self, context):
        if self.model and self.lookup:
            if isinstance(self.lookup[1], template.Variable):
                try:
                    lookup_val = self.lookup[1].resolve(context)
                except template.VariableDoesNotExist, e:
                    log.warning('BoxNode: Template variable does not exist. var_name=%s', self.lookup[1].var)
                    raise ObjectNotFoundOrInvalid()

            else:
                lookup_val = self.lookup[1]

            try:
                obj = get_cached_object(self.model, **{self.lookup[0] : lookup_val})
            except (models.ObjectDoesNotExist, AssertionError), e:
                log.warning('BoxNode: %s (%s : %s)', str(e), self.lookup[0], lookup_val)
                raise ObjectNotFoundOrInvalid()
        else:
            try:
                obj = self.var.resolve(context)
            except template.VariableDoesNotExist, e:
                log.warning('BoxNode: Template variable does not exist. var_name=%s', self.var.var)
                raise ObjectNotFoundOrInvalid()

            if not obj:
                raise ObjectNotFoundOrInvalid()
        return obj

    def render(self, context):

        try:
            obj = self.get_obj(context)
        except ObjectNotFoundOrInvalid, e:
            return ''

        box = getattr(obj, 'box_class', Box)(obj, self.box_type, self.nodelist)

        if not box or not box.obj:
            log.warning('BoxNode: Box does not exists.')
            return ''

        # render the box
        return box.render(context)

@register.tag('box')
def do_box(parser, token):
    """
    Tag Node representing our idea of a reusable box. It can handle multiple
    parameters in its body which will then be accessible via ``{{ box.params
    }}`` in the template being rendered.

    .. note::
        The inside of the box will be rendered only when redering the box in
        current context and the ``object`` template variable will be present
        and set to the target of the box.

    Author of any ``Model`` can specify it's own ``box_class`` which enables
    custom handling of some content types (boxes for polls for example need
    some extra information to render properly).

    Boxes, same as :ref:`core-views`, look for most specific template for a given
    object an only fall back to more generic template if the more specific one
    doesn't exist. The list of templates it looks for:

    * ``box/category/<tree_path>/content_type/<app>.<model>/<slug>/<box_name>.html``
    * ``box/category/<tree_path>/content_type/<app>.<model>/<box_name>.html``
    * ``box/category/<tree_path>/content_type/<app>.<model>/box.html``
    * ``box/content_type/<app>.<model>/<slug>/<box_name>.html``
    * ``box/content_type/<app>.<model>/<box_name>.html``
    * ``box/content_type/<app>.<model>/box.html``
    * ``box/<box_name>.html``
    * ``box/box.html``

    .. note::
        Since boxes work for all models (and not just ``Publishable`` subclasses),
        some template names don't exist for some model classes, for example
        ``Photo`` model doesn't have a link to ``Category`` so that cannot be used.

    Boxes are always rendered in current context with added variables:

    * ``object`` - object being represented
    * ``box`` - instance of ``ella.core.box.Box``

    Usage::

        {% box <boxtype> for <app.model> with <field> <value> %}
            param_name: value
            param_name_2: {{ some_var }}
        {% endbox %}

        {% box <boxtype> for <var_name> %}
            ...
        {% endbox %}

    Parameters:

        ==================================  ================================================
        Option                              Description
        ==================================  ================================================
        ``boxtype``                         Name of the box to use
        ``app.model``                       Model class to use
        ``field``                           Field on which to do DB lookup
        ``value``                           Value for DB lookup
        ``var_name``                        Template variable to get the instance from
        ==================================  ================================================

    Examples::

        {% box home_listing for articles.article with slug "some-slug" %}{% endbox %}

        {% box home_listing for articles.article with pk object_id %}
            template_name : {{object.get_box_template}}
        {% endbox %}

        {% box home_listing for article %}{% endbox %}
    """
    bits = token.split_contents()

    nodelist = parser.parse(('end' + bits[0],))
    parser.delete_first_token()
    return _parse_box(nodelist, bits)

def _parse_box(nodelist, bits):
    # {% box BOXTYPE for var_name %}                {% box BOXTYPE for content.type with PK_FIELD PK_VALUE %}
    if (len(bits) != 4 or bits[2] != 'for') and (len(bits) != 7 or bits[2] != 'for' or bits[4] != 'with'):
        raise template.TemplateSyntaxError, "{% box BOXTYPE for content.type with FIELD VALUE %} or {% box BOXTYPE for var_name %}"

    if len(bits) == 4:
        # var_name
        return BoxNode(bits[1], nodelist, var=template.Variable(bits[3]))
    else:
        model = models.get_model(*bits[3].split('.'))
        if model is None:
            return EmptyNode()

        lookup_val = template.Variable(bits[6])
        try:
            lookup_val = lookup_val.resolve({})
        except template.VariableDoesNotExist:
            pass
        return BoxNode(bits[1], nodelist, model=model, lookup=(smart_str(bits[5]), lookup_val))
