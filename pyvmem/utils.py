from __future__ import unicode_literals


def parse_hexnum(value):
    """Parse numeric constant from string.

    >>> parse_hexnum("f4521403007b08f1")
    'f4521403007b08f1'

    >>> parse_hexnum("0xf4521403007b08f1")
    'f4521403007b08f1'

    >>> parse_hexnum("\x1b")
    Traceback (most recent call last):
    ...
    ValueError: invalid literal for int() with base 16: '\x1b'

    >>> parse_hexnum(111)
    Traceback (most recent call last):
    ...
    ValueError: 'value' must be <type 'str'>, not <type 'int'>

    >>> parse_hexnum(10L)
    Traceback (most recent call last):
    ...
    ValueError: 'value' must be <type 'str'>, not <type 'long'>
    """

    if not isinstance(value, basestring):
        raise ValueError(
            "'value' must be %s, not %s" % (str, type(value),))

    return "{0:0{1}x}".format(int(value, 16), 16)


def hexnum_to_hexstr(value):
    """Convert valid hexnum to hexstr.

    >>> hexnum_to_hexstr("f4521403007b08f1")
    '\xf4R\x14\x03\x00{\x08\xf1'
    """

    import binascii
    return binascii.unhexlify(value)


def hexnum_to_wwn(value):
    """Validate hexnum and generate wwn address.

    >>> hexnum_to_wwn("f4521403007b08f1")
    'wwn.f4:52:14:03:00:7b:08:f1'

    >>> hexnum_to_wwn("0xf4521403007b08f1")
    'wwn.f4:52:14:03:00:7b:08:f1'
    """
    value = parse_hexnum(value)
    return "wwn." + ":".join(
        "".join(pair) for pair in zip(*[iter(value)] * 2)
    )


def hexnum_to_guid(value):
    """Validate hexnum and generate guid address.

    >>> hexnum_to_guid("f4521403007b08f1")
    'guid.f452:1403:007b:08f1'

    >>> hexnum_to_guid("0xf4521403007b08f1")
    'guid.f452:1403:007b:08f1'
    """
    value = parse_hexnum(value)
    return "guid." + ":".join(
        "".join(pair) for pair in zip(*[iter(value)] * 4)
    )
