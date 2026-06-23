---
standard_id: example
version: 1.0
profile: default
languages: [all]
source: example.md
---

# 通用规则

## GENERAL-ERROR-001

所有外部输入、I/O、网络、数据库和序列化操作必须处理失败路径。不得静默吞掉异常；错误信息不得泄露密钥、令牌或个人数据。

## GENERAL-RESOURCE-001

文件、锁、连接、事务、内存和硬件资源必须在所有正常与异常路径中成对释放。优先使用语言提供的作用域或自动资源管理机制。

# C/C++

## C-BOUNDS-001

数组、指针运算、字符串复制和缓冲区长度计算必须证明边界安全，并考虑整数溢出和终止符空间。

## C-ISR-001

中断服务程序中禁止阻塞锁、动态内存分配、无界循环和同步日志输出。

## C-DMA-001

DMA 缓冲区必须满足对齐、生命周期和 cache 一致性要求；CPU 与设备切换所有权时必须执行目标平台要求的 clean/invalidate 操作。

# Web

## WEB-XSS-001

HTML、JavaScript 和模板中的不可信数据必须按输出上下文编码。不得以字符串拼接方式构造可执行 HTML、脚本或事件处理器。
