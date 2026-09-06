"""
تشفير والتحقق من كلمات مرور المستخدمين.

إصلاح أمني مهم: كان النظام يستخدم SHA-256 مباشر بدون أي "ملح" (salt) لحفظ
كلمات المرور. المشكلة بهذا:
1. SHA-256 مصمم يكون *سريع* (خوارزمية تجزئة عامة) - وهذا بالضبط عكس اللي
   تحتاجه لحفظ كلمات المرور. سرعته تخليه سهل الكسر بمحاولة ملايين الاحتمالات
   بالثانية (brute force) لو انسرقت قاعدة البيانات.
2. بدون "ملح" مختلف لكل مستخدم، أي شخص عنده جداول جاهزة لهاشات شائعة
   (rainbow tables) يقدر يكسر كل كلمات المرور المتشابهة دفعة وحدة.

الحل هنا: PBKDF2-HMAC-SHA256 بملح عشوائي منفصل لكل مستخدم و260,000 دورة
تكرار (يطابق توصيات OWASP الحالية لـ PBKDF2-SHA256) - يخلي كل محاولة تخمين
كلمة مرور تاخذ وقت محسوس بدل أجزاء الثانية، وملح مختلف لكل مستخدم يمنع
هجمات rainbow table بالكامل. هذا باستخدام مكتبة Python القياسية بس
(hashlib) بدون أي اعتمادية خارجية جديدة.

التوافق مع الحسابات القديمة: أي كلمة مرور محفوظة بالصيغة القديمة (SHA-256
بدون ملح، بدون علامة $) لسا تشتغل وقت تسجيل الدخول (verify_password تتعرف
عليها تلقائيًا) - وتترقّى تلقائيًا للصيغة الجديدة الأقوى بأول تسجيل دخول
ناجح (شوف login_window.py) بدون ما يحس فيها المستخدم أو يحتاج يغيّر شي.
"""
import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 260_000


def hash_password(raw: str, salt: bytes = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(raw: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if "$" not in stored_hash:
        # صيغة قديمة (SHA-256 بدون ملح) - للتوافق مع حسابات قبل هذا الإصلاح
        return hmac.compare_digest(hashlib.sha256(raw.encode("utf-8")).hexdigest(), stored_hash)
    salt_hex, hash_hex = stored_hash.split("$", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    derived = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(derived.hex(), hash_hex)


def is_legacy_hash(stored_hash: str) -> bool:
    """يتحقق إذا كانت كلمة المرور محفوظة بالصيغة القديمة الضعيفة (بدون
    ملح) - يستخدم لترقيتها تلقائيًا بعد تسجيل دخول ناجح."""
    return bool(stored_hash) and "$" not in stored_hash
