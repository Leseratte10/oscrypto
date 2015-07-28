# coding: utf-8
from __future__ import unicode_literals, division, absolute_import, print_function

import sys

from asn1crypto import keys, x509

from .._ffi import new, unwrap, bytes_from_buffer, buffer_from_bytes, deref
from ._security import Security, security_const, handle_sec_error
from ._core_foundation import CoreFoundation, CFHelpers, handle_cf_error
from ..keys import parse_public, parse_certificate, parse_private, parse_pkcs12
from ..errors import SignatureError, PrivateKeyError
from .._pkcs1 import add_pss_padding, verify_pss_padding

if sys.version_info < (3,):
    str_cls = unicode  #pylint: disable=E0602
    byte_cls = str
else:
    str_cls = str
    byte_cls = bytes



class PrivateKey():
    """
    Container for the OS X Security Framework representation of a private key
    """

    sec_key_ref = None
    asn1 = None

    def __init__(self, sec_key_ref, asn1):
        """
        :param sec_key_ref:
            A Security framework SecKeyRef value from loading/importing the
            key

        :param asn1:
            An asn1crypto.keys.PrivateKeyInfo object
        """

        self.sec_key_ref = sec_key_ref
        self.asn1 = asn1

    @property
    def algo(self):
        """
        :return:
            A unicode string of "rsa", "dsa" or "ec"
        """

        return self.asn1.algorithm

    @property
    def bit_size(self):
        """
        :return:
            The number of bits in the key, as an integer
        """

        return self.asn1.bit_size

    @property
    def byte_size(self):
        """
        :return:
            The number of bytes in the key, as an integer
        """

        return self.asn1.byte_size

    def __del__(self):
        if self.sec_key_ref:
            CoreFoundation.CFRelease(self.sec_key_ref)
            self.sec_key_ref = None


class PublicKey(PrivateKey):
    """
    Container for the OS X Security Framework representation of a public key
    """

    def __init__(self, sec_key_ref, asn1):
        """
        :param sec_key_ref:
            A Security framework SecKeyRef value from loading/importing the
            key

        :param asn1:
            An asn1crypto.keys.PublicKeyInfo object
        """

        PrivateKey.__init__(self, sec_key_ref, asn1)


class Certificate():
    """
    Container for the OS X Security Framework representation of a certificate
    """

    sec_certificate_ref = None
    asn1 = None
    _public_key = None

    def __init__(self, sec_certificate_ref, asn1):
        """
        :param sec_certificate_ref:
            A Security framework SecCertificateRef value from loading/importing
            the certificate

        :param asn1:
            An asn1crypto.x509.Certificate object
        """

        self.sec_certificate_ref = sec_certificate_ref
        self.asn1 = asn1

    @property
    def algo(self):
        """
        :return:
            A unicode string of "rsa", "dsa" or "ec"
        """

        return self.public_key.algo

    @property
    def bit_size(self):
        """
        :return:
            The number of bits in the public key, as an integer
        """

        return self.public_key.bit_size

    @property
    def byte_size(self):
        """
        :return:
            The number of bytes in the public key, as an integer
        """

        return self.public_key.byte_size

    @property
    def sec_key_ref(self):
        """
        :return:
            The SecKeyRef of the public key
        """

        return self.public_key.sec_key_ref

    @property
    def public_key(self):
        """
        :return:
            The PublicKey object for the public key this certificate contains
        """

        if not self._public_key and self.sec_certificate_ref:
            sec_public_key_ref_pointer = new(Security, 'SecKeyRef *')
            res = Security.SecCertificateCopyPublicKey(self.sec_certificate_ref, sec_public_key_ref_pointer)
            handle_sec_error(res)
            sec_public_key_ref = unwrap(sec_public_key_ref_pointer)
            self._public_key = PublicKey(sec_public_key_ref, self.asn1['tbs_certificate']['subject_public_key_info'])

        return self._public_key

    def __del__(self):
        if self._public_key:
            self._public_key.__del__()
            self._public_key = None

        if self.sec_certificate_ref:
            CoreFoundation.CFRelease(self.sec_certificate_ref)
            self.sec_certificate_ref = None


def load_certificate(source):
    """
    Loads an x509 certificate into a Certificate object

    :param source:
        A byte string of file contents, a unicode string filename or an
        asn1crypto.x509.Certificate object

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A Certificate object
    """

    if isinstance(source, x509.Certificate):
        certificate = source

    elif isinstance(source, byte_cls):
        certificate, _ = parse_certificate(source)

    elif isinstance(source, str_cls):
        with open(source, 'rb') as f:
            certificate, _ = parse_certificate(f.read())

    else:
        raise ValueError('source must be a byte string, unicode string or asn1crypto.x509.Certificate object, not %s' % source.__class__.__name__)

    return _load_x509(certificate)


def _load_x509(certificate):
    """
    Loads an ASN.1 object of an x509 certificate into a Certificate object

    :param certificate:
        An asn1crypto.x509.Certificate object

    :return:
        A Certificate object
    """

    source = certificate.dump()

    cf_source = None
    try:
        cf_source = CFHelpers.cf_data_from_bytes(source)
        sec_key_ref = Security.SecCertificateCreateWithData(CoreFoundation.kCFAllocatorDefault, cf_source)
        return Certificate(sec_key_ref, certificate)

    finally:
        if cf_source:
            CoreFoundation.CFRelease(cf_source)


def load_private_key(source, password=None):
    """
    Loads a private key into a PrivateKey object

    :param source:
        A byte string of file contents, a unicode string filename or an
        asn1crypto.keys.PrivateKeyInfo object

    :param password:
        A byte or unicode string to decrypt the private key file. Unicode
        strings will be encoded using UTF-8. Not used is the source is a
        PrivateKeyInfo object.

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A PrivateKey object
    """

    if isinstance(source, keys.PrivateKeyInfo):
        private_object = source

    else:
        if password is not None:
            if isinstance(password, str_cls):
                password = password.encode('utf-8')
            if not isinstance(password, byte_cls):
                raise ValueError('password must be a byte string, not %s' % password.__class__.__name__)

        if isinstance(source, str_cls):
            with open(source, 'rb') as f:
                source = f.read()

        elif not isinstance(source, byte_cls):
            raise ValueError('source must be a byte string, unicode string or asn1crypto.keys.PrivateKeyInfo object, not %s' % source.__class__.__name__)

        private_object, _ = parse_private(source, password)

    return _load_key(private_object)


def load_public_key(source):
    """
    Loads a public key into a PublicKey object

    :param source:
        A byte string of file contents, a unicode string filename or an
        asn1crypto.keys.PublicKeyInfo object

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A PublicKey object
    """

    if isinstance(source, keys.PublicKeyInfo):
        public_key = source

    elif isinstance(source, byte_cls):
        public_key, _ = parse_public(source)

    elif isinstance(source, str_cls):
        with open(source, 'rb') as f:
            public_key, _ = parse_public(f.read())

    else:
        raise ValueError('source must be a byte string, unicode string or asn1crypto.keys.PublicKeyInfo object, not %s' % public_key.__class__.__name__)

    return _load_key(public_key)


def _load_key(key_object):
    """
    Common code to load public and private keys into PublicKey and PrivateKey
    objects

    :param key_object:
        An asn1crypto.keys.PublicKeyInfo or asn1crypto.keys.PrivateKeyInfo
        object

    :return:
        A PublicKey or PrivateKey object
    """

    if key_object.algorithm == 'ec':
        curve_type, details = key_object.curve
        if curve_type != 'named':
            raise PrivateKeyError('OS X only supports EC keys using named curves')
        if details not in {'secp256r1', 'secp384r1', 'secp521r1'}:
            raise PrivateKeyError('OS X only supports EC keys using the named curves secp256r1, secp384r1 and secp521r1')

    elif key_object.algorithm == 'dsa' and key_object.hash_algo == 'sha2':
        raise PrivateKeyError('OS X only supports DSA keys based on SHA1 (2048 bits or less) - this key is based on SHA2 and is %s bits' % key_object.bit_size)

    if isinstance(key_object, keys.PublicKeyInfo):
        source = key_object.dump()
        key_class = Security.kSecAttrKeyClassPublic
    else:
        source = key_object.unwrap().dump()
        key_class = Security.kSecAttrKeyClassPrivate

    cf_source = None
    cf_dict = None
    cf_output = None

    try:
        cf_source = CFHelpers.cf_data_from_bytes(source)
        key_type = {
            'dsa': Security.kSecAttrKeyTypeDSA,
            'ec': Security.kSecAttrKeyTypeECDSA,
            'rsa': Security.kSecAttrKeyTypeRSA,
        }[key_object.algorithm]
        cf_dict = CFHelpers.cf_dictionary_from_pairs([
            (Security.kSecAttrKeyType, key_type),
            (Security.kSecAttrKeyClass, key_class),
            (Security.kSecAttrCanSign, CoreFoundation.kCFBooleanTrue),
            (Security.kSecAttrCanVerify, CoreFoundation.kCFBooleanTrue),
        ])
        error_pointer = new(CoreFoundation, 'CFErrorRef *')
        sec_key_ref = Security.SecKeyCreateFromData(cf_dict, cf_source, error_pointer)
        handle_cf_error(error_pointer)

        if key_class == Security.kSecAttrKeyClassPublic:
            return PublicKey(sec_key_ref, key_object)

        if key_class == Security.kSecAttrKeyClassPrivate:
            return PrivateKey(sec_key_ref, key_object)

    finally:
        if cf_source:
            CoreFoundation.CFRelease(cf_source)
        if cf_dict:
            CoreFoundation.CFRelease(cf_dict)
        if cf_output:
            CoreFoundation.CFRelease(cf_output)


def load_pkcs12(source, password=None):
    """
    Loads a .p12 or .pfx file into a PrivateKey object and one or more
    Certificates objects

    :param source:
        A byte string of file contents or a unicode string filename

    :param password:
        A byte or unicode string to decrypt the PKCS12 file. Unicode strings
        will be encoded using UTF-8.

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A three-element tuple containing (PrivateKey, Certificate, [Certificate, ...])
    """

    if password is not None:
        if isinstance(password, str_cls):
            password = password.encode('utf-8')
        if not isinstance(password, byte_cls):
            raise ValueError('password must be a byte string, not %s' % password.__class__.__name__)

    if isinstance(source, str_cls):
        with open(source, 'rb') as f:
            source = f.read()

    elif not isinstance(source, byte_cls):
        raise ValueError('source must be a byte string or a unicode string, not %s' % source.__class__.__name__)

    key_info, cert_info, extra_certs_info = parse_pkcs12(source, password)

    key = None
    cert = None

    if key_info:
        key = _load_key(key_info[0])

    if cert_info:
        cert = _load_x509(cert_info[0])

    extra_certs = [_load_x509(info[0]) for info in extra_certs_info]

    return (key, cert, extra_certs)


def rsa_pkcs1v15_encrypt(certificate_or_public_key, data):
    """
    Encrypts a byte string using an RSA public key or certificate. Uses PKCS#1
    v1.5 padding.

    :param certificate_or_public_key:
        A PublicKey or Certificate object

    :param data:
        A byte string, with a maximum length 11 bytes less than the key length
        (in bytes)

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the encrypted data
    """

    if not isinstance(certificate_or_public_key, (Certificate, PublicKey)):
        raise ValueError('certificate_or_public_key must be an instance of the Certificate or PublicKey class, not %s' % certificate_or_public_key.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    key_length = certificate_or_public_key.byte_size
    buffer = buffer_from_bytes(key_length)
    output_length = new(Security, 'size_t *', key_length)
    result = Security.SecKeyEncrypt(certificate_or_public_key.sec_key_ref, security_const.kSecPaddingPKCS1, data, len(data), buffer, output_length)
    handle_sec_error(result)

    return bytes_from_buffer(buffer, deref(output_length))


def rsa_pkcs1v15_decrypt(private_key, ciphertext):
    """
    Decrypts a byte string using an RSA private key. Uses PKCS#1 v1.5 padding.

    :param private_key:
        A PrivateKey object

    :param ciphertext:
        A byte string of the encrypted data

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the original plaintext
    """

    if not isinstance(private_key, PrivateKey):
        raise ValueError('private_key must an instance of the PrivateKey class, not %s' % private_key.__class__.__name__)

    if not isinstance(ciphertext, byte_cls):
        raise ValueError('data must be a byte string, not %s' % ciphertext.__class__.__name__)

    key_length = private_key.byte_size
    buffer = buffer_from_bytes(key_length)
    output_length = new(Security, 'size_t *', key_length)
    result = Security.SecKeyDecrypt(private_key.sec_key_ref, security_const.kSecPaddingPKCS1, ciphertext, len(ciphertext), buffer, output_length)
    handle_sec_error(result)

    return bytes_from_buffer(buffer, deref(output_length))


def rsa_oaep_encrypt(certificate_or_public_key, data):
    """
    Encrypts a byte string using an RSA public key or certificate. Uses PKCS#1
    OAEP padding with SHA1.

    :param certificate_or_public_key:
        A PublicKey or Certificate object

    :param data:
        A byte string, with a maximum length 41 bytes (or more) less than the
        key length (in bytes)

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the encrypted data
    """

    return _encrypt(certificate_or_public_key, data, Security.kSecPaddingOAEPKey)


def rsa_oaep_decrypt(private_key, ciphertext):
    """
    Decrypts a byte string using an RSA private key. Uses PKCS#1 OAEP padding
    with SHA1.

    :param private_key:
        A PrivateKey object

    :param ciphertext:
        A byte string of the encrypted data

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the original plaintext
    """

    return _decrypt(private_key, ciphertext, Security.kSecPaddingOAEPKey)


def _encrypt(certificate_or_public_key, data, padding):
    """
    Encrypts plaintext using an RSA public key or certificate

    :param certificate_or_public_key:
        A Certificate or PublicKey object

    :param data:
        The plaintext - a byte string

    :param padding:
        The padding mode to use, specified as a kSecPadding*Key value

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the ciphertext
    """

    if not isinstance(certificate_or_public_key, (Certificate, PublicKey)):
        raise ValueError('certificate_or_public_key must be an instance of the Certificate or PublicKey class, not %s' % certificate_or_public_key.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    if not padding:
        raise ValueError('padding must be specified')

    cf_data = None
    sec_transform = None

    try:
        cf_data = CFHelpers.cf_data_from_bytes(data)

        error_pointer = new(CoreFoundation, 'CFErrorRef *')
        sec_transform = Security.SecEncryptTransformCreate(certificate_or_public_key.sec_key_ref, error_pointer)
        handle_cf_error(error_pointer)

        if padding:
            Security.SecTransformSetAttribute(sec_transform, Security.kSecPaddingKey, padding, error_pointer)
            handle_cf_error(error_pointer)

        Security.SecTransformSetAttribute(sec_transform, Security.kSecTransformInputAttributeName, cf_data, error_pointer)
        handle_cf_error(error_pointer)

        ciphertext = Security.SecTransformExecute(sec_transform, error_pointer)
        handle_cf_error(error_pointer)

        return CFHelpers.cf_data_to_bytes(ciphertext)

    finally:
        if cf_data:
            CoreFoundation.CFRelease(cf_data)
        if sec_transform:
            CoreFoundation.CFRelease(sec_transform)


def _decrypt(private_key, ciphertext, padding):
    """
    Decrypts RSA ciphertext using a private key

    :param private_key:
        A PrivateKey object

    :param ciphertext:
        The ciphertext - a byte string

    :param padding:
        The padding mode to use, specified as a kSecPadding*Key value

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the plaintext
    """

    if not isinstance(private_key, PrivateKey):
        raise ValueError('private_key must be an instance of the PrivateKey class, not %s' % private_key.__class__.__name__)

    if not isinstance(ciphertext, byte_cls):
        raise ValueError('ciphertext must be a byte string, not %s' % ciphertext.__class__.__name__)

    if not padding:
        raise ValueError('padding must be specified')

    cf_data = None
    sec_transform = None

    try:
        cf_data = CFHelpers.cf_data_from_bytes(ciphertext)

        error_pointer = new(CoreFoundation, 'CFErrorRef *')
        sec_transform = Security.SecDecryptTransformCreate(private_key.sec_key_ref, error_pointer)
        handle_cf_error(error_pointer)

        Security.SecTransformSetAttribute(sec_transform, Security.kSecPaddingKey, padding, error_pointer)
        handle_cf_error(error_pointer)

        Security.SecTransformSetAttribute(sec_transform, Security.kSecTransformInputAttributeName, cf_data, error_pointer)
        handle_cf_error(error_pointer)

        plaintext = Security.SecTransformExecute(sec_transform, error_pointer)
        handle_cf_error(error_pointer)

        return CFHelpers.cf_data_to_bytes(plaintext)

    finally:
        if cf_data:
            CoreFoundation.CFRelease(cf_data)
        if sec_transform:
            CoreFoundation.CFRelease(sec_transform)


def rsa_pkcs1v15_verify(certificate_or_public_key, signature, data, hash_algorithm):
    """
    Verifies an RSASSA-PKCS-v1.5 signature

    :param certificate_or_public_key:
        A Certificate or PublicKey instance to verify the signature with

    :param signature:
        A byte string of the signature to verify

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework
        oscrypto.errors.SignatureError - when the signature is determined to be invalid
    """

    if certificate_or_public_key.algo != 'rsa':
        raise ValueError('The key specified is not an RSA public key')

    return _verify(certificate_or_public_key, signature, data, hash_algorithm)


def rsa_pss_verify(certificate_or_public_key, signature, data, hash_algorithm):
    """
    Verifies an RSASSA-PSS signature. For the PSS padding the mask gen algorithm
    will be mgf1 using the same hash algorithm as the signature. The salt length
    with be the length of the hash algorithm, and the trailer field with be the
    standard 0xBC byte.

    :param certificate_or_public_key:
        A Certificate or PublicKey instance to verify the signature with

    :param signature:
        A byte string of the signature to verify

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework
        oscrypto.errors.SignatureError - when the signature is determined to be invalid
    """

    if not isinstance(certificate_or_public_key, (Certificate, PublicKey)):
        raise ValueError('certificate_or_public_key must be an instance of the Certificate or PublicKey class, not %s' % certificate_or_public_key.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    if certificate_or_public_key.algo != 'rsa':
        raise ValueError('The key specified is not an RSA public key')

    hash_length = {
        'sha1': 20,
        'sha224': 28,
        'sha256': 32,
        'sha384': 48,
        'sha512': 64
    }.get(hash_algorithm, 0)

    plaintext = _encrypt(certificate_or_public_key, signature, Security.kSecPaddingNoneKey)
    if not verify_pss_padding(hash_algorithm, hash_length, certificate_or_public_key.bit_size, data, plaintext):
        raise SignatureError('Signature is invalid')


def dsa_verify(certificate_or_public_key, signature, data, hash_algorithm):
    """
    Verifies a DSA signature

    :param certificate_or_public_key:
        A Certificate or PublicKey instance to verify the signature with

    :param signature:
        A byte string of the signature to verify

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework
        oscrypto.errors.SignatureError - when the signature is determined to be invalid
    """

    if certificate_or_public_key.algo != 'dsa':
        raise ValueError('The key specified is not a DSA public key')

    return _verify(certificate_or_public_key, signature, data, hash_algorithm)


def ecdsa_verify(certificate_or_public_key, signature, data, hash_algorithm):
    """
    Verifies an ECDSA signature

    :param certificate_or_public_key:
        A Certificate or PublicKey instance to verify the signature with

    :param signature:
        A byte string of the signature to verify

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework
        oscrypto.errors.SignatureError - when the signature is determined to be invalid
    """

    if certificate_or_public_key.algo != 'ec':
        raise ValueError('The key specified is not an EC public key')

    return _verify(certificate_or_public_key, signature, data, hash_algorithm)


def _verify(certificate_or_public_key, signature, data, hash_algorithm):
    """
    Verifies an RSA, DSA or ECDSA signature

    :param certificate_or_public_key:
        A Certificate or PublicKey instance to verify the signature with

    :param signature:
        A byte string of the signature to verify

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework
        oscrypto.errors.SignatureError - when the signature is determined to be invalid
    """

    if not isinstance(certificate_or_public_key, (Certificate, PublicKey)):
        raise ValueError('certificate_or_public_key must be an instance of the Certificate or PublicKey class, not %s' % certificate_or_public_key.__class__.__name__)

    if not isinstance(signature, byte_cls):
        raise ValueError('signature must be a byte string, not %s' % signature.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    if hash_algorithm not in {'md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512'}:
        raise ValueError('hash_algorithm must be one of "md5", "sha1", "sha224", "sha256", "sha384", "sha512", not %s' % repr(hash_algorithm))

    cf_signature = None
    cf_data = None
    cf_hash_length = None
    sec_transform = None

    try:
        error_pointer = new(CoreFoundation, 'CFErrorRef *')
        cf_signature = CFHelpers.cf_data_from_bytes(signature)
        sec_transform = Security.SecVerifyTransformCreate(certificate_or_public_key.sec_key_ref, cf_signature, error_pointer)
        handle_cf_error(error_pointer)

        hash_constant = {
            'md5': Security.kSecDigestMD5,
            'sha1': Security.kSecDigestSHA1,
            'sha224': Security.kSecDigestSHA2,
            'sha256': Security.kSecDigestSHA2,
            'sha384': Security.kSecDigestSHA2,
            'sha512': Security.kSecDigestSHA2
        }[hash_algorithm]

        Security.SecTransformSetAttribute(sec_transform, Security.kSecDigestTypeAttribute, hash_constant, error_pointer)
        handle_cf_error(error_pointer)

        if hash_algorithm in {'sha224', 'sha256', 'sha384', 'sha512'}:
            hash_length = {
                'sha224': 224,
                'sha256': 256,
                'sha384': 384,
                'sha512': 512
            }[hash_algorithm]

            cf_hash_length = CFHelpers.cf_number_from_integer(hash_length)

            Security.SecTransformSetAttribute(sec_transform, Security.kSecDigestLengthAttribute, cf_hash_length, error_pointer)
            handle_cf_error(error_pointer)

        if certificate_or_public_key.algo == 'rsa':
            Security.SecTransformSetAttribute(sec_transform, Security.kSecPaddingKey, Security.kSecPaddingPKCS1Key, error_pointer)
            handle_cf_error(error_pointer)

        cf_data = CFHelpers.cf_data_from_bytes(data)
        Security.SecTransformSetAttribute(sec_transform, Security.kSecTransformInputAttributeName, cf_data, error_pointer)
        handle_cf_error(error_pointer)

        res = Security.SecTransformExecute(sec_transform, error_pointer)
        handle_cf_error(error_pointer)

        res = bool(CoreFoundation.CFBooleanGetValue(res))

        if not res:
            raise SignatureError('Signature is invalid')

    finally:
        if sec_transform:
            CoreFoundation.CFRelease(sec_transform)
        if cf_signature:
            CoreFoundation.CFRelease(cf_signature)
        if cf_data:
            CoreFoundation.CFRelease(cf_data)
        if cf_hash_length:
            CoreFoundation.CFRelease(cf_hash_length)


def rsa_pkcs1v15_sign(private_key, data, hash_algorithm):
    """
    Generates an RSASSA-PKCS-v1.5 signature

    :param private_key:
        The PrivateKey to generate the signature with

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the signature
    """

    if private_key.algo != 'rsa':
        raise ValueError('The key specified is not an RSA private key')

    return _sign(private_key, data, hash_algorithm)


def rsa_pss_sign(private_key, data, hash_algorithm):
    """
    Generates an RSASSA-PSS signature. For the PSS padding the mask gen
    algorithm will be mgf1 using the same hash algorithm as the signature. The
    salt length with be the length of the hash algorithm, and the trailer field
    with be the standard 0xBC byte.

    :param private_key:
        The PrivateKey to generate the signature with

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the signature
    """

    if not isinstance(private_key, PrivateKey):
        raise ValueError('private_key must be an instance of the PrivateKey class, not %s' % private_key.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    if private_key.algo != 'rsa':
        raise ValueError('The key specified is not an RSA private key')

    hash_length = {
        'sha1': 20,
        'sha224': 28,
        'sha256': 32,
        'sha384': 48,
        'sha512': 64
    }.get(hash_algorithm, 0)

    encoded_data = add_pss_padding(hash_algorithm, hash_length, private_key.bit_size, data)
    return _decrypt(private_key, encoded_data, Security.kSecPaddingNoneKey)


def dsa_sign(private_key, data, hash_algorithm):
    """
    Generates a DSA signature

    :param private_key:
        The PrivateKey to generate the signature with

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the signature
    """

    if private_key.algo != 'dsa':
        raise ValueError('The key specified is not a DSA private key')

    return _sign(private_key, data, hash_algorithm)


def ecdsa_sign(private_key, data, hash_algorithm):
    """
    Generates an ECDSA signature

    :param private_key:
        The PrivateKey to generate the signature with

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the signature
    """

    if private_key.algo != 'ec':
        raise ValueError('The key specified is not an EC private key')

    return _sign(private_key, data, hash_algorithm)


def _sign(private_key, data, hash_algorithm):
    """
    Generates an RSA, DSA or ECDSA signature

    :param private_key:
        The PrivateKey to generate the signature with

    :param data:
        A byte string of the data the signature is for

    :param hash_algorithm:
        A unicode string of "md5", "sha1", "sha224", "sha256", "sha384" or "sha512"

    :raises:
        ValueError - when any of the parameters are of the wrong type or value
        OSError - when an error is returned by the OS X Security Framework

    :return:
        A byte string of the signature
    """

    if not isinstance(private_key, PrivateKey):
        raise ValueError('private_key must be an instance of PrivateKey, not %s' % private_key.__class__.__name__)

    if not isinstance(data, byte_cls):
        raise ValueError('data must be a byte string, not %s' % data.__class__.__name__)

    if hash_algorithm not in {'md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512'}:
        raise ValueError('hash_algorithm must be one of "md5", "sha1", "sha256", "sha384", "sha512", not %s' % repr(hash_algorithm))

    cf_signature = None
    cf_data = None
    cf_hash_length = None
    sec_transform = None

    try:
        error_pointer = new(CoreFoundation, 'CFErrorRef *')
        sec_transform = Security.SecSignTransformCreate(private_key.sec_key_ref, error_pointer)
        handle_cf_error(error_pointer)

        hash_constant = {
            'md5': Security.kSecDigestMD5,
            'sha1': Security.kSecDigestSHA1,
            'sha224': Security.kSecDigestSHA2,
            'sha256': Security.kSecDigestSHA2,
            'sha384': Security.kSecDigestSHA2,
            'sha512': Security.kSecDigestSHA2
        }[hash_algorithm]

        Security.SecTransformSetAttribute(sec_transform, Security.kSecDigestTypeAttribute, hash_constant, error_pointer)
        handle_cf_error(error_pointer)

        if hash_algorithm in {'sha224', 'sha256', 'sha384', 'sha512'}:
            hash_length = {
                'sha224': 224,
                'sha256': 256,
                'sha384': 384,
                'sha512': 512
            }[hash_algorithm]

            cf_hash_length = CFHelpers.cf_number_from_integer(hash_length)

            Security.SecTransformSetAttribute(sec_transform, Security.kSecDigestLengthAttribute, cf_hash_length, error_pointer)
            handle_cf_error(error_pointer)

        if private_key.algo == 'rsa':
            Security.SecTransformSetAttribute(sec_transform, Security.kSecPaddingKey, Security.kSecPaddingPKCS1Key, error_pointer)
            handle_cf_error(error_pointer)

        cf_data = CFHelpers.cf_data_from_bytes(data)
        Security.SecTransformSetAttribute(sec_transform, Security.kSecTransformInputAttributeName, cf_data, error_pointer)
        handle_cf_error(error_pointer)

        cf_signature = Security.SecTransformExecute(sec_transform, error_pointer)
        handle_cf_error(error_pointer)

        return CFHelpers.cf_data_to_bytes(cf_signature)

    finally:
        if sec_transform:
            CoreFoundation.CFRelease(sec_transform)
        if cf_signature:
            CoreFoundation.CFRelease(cf_signature)
        if cf_data:
            CoreFoundation.CFRelease(cf_data)
        if cf_hash_length:
            CoreFoundation.CFRelease(cf_hash_length)

