// Source-language keys keep the existing UI copy searchable. Values are English and Indonesian.
export const messages: Record<string, readonly [string, string]> = {
  "私聊里的待办": [
    "To-dos in private chats",
    "Tugas dari chat pribadi"
  ],
  "开启后，Relay 以你的身份读你和常联系同事之间的私聊，找出别人让你做的事和你在等别人的事，有了结果自动结束。私聊内容只用于你自己的事项。": [
    "When on, Relay reads your private chats with frequent contacts (as you) to find what others ask of you and what you are waiting on, and closes them when there is a result. Private messages are only used for your own items.",
    "Jika aktif, Relay membaca chat pribadi Anda dengan kontak yang sering dihubungi (sebagai Anda) untuk menemukan permintaan orang lain dan hal yang Anda tunggu, lalu menutupnya saat ada hasil. Pesan pribadi hanya dipakai untuk urusan Anda sendiri."
  ],
  "飞书后台开通了新功能，重新登录一次就能用上（例如看私聊里对方的回复）。": [
    "New Feishu permissions were enabled. Log in again to use them (e.g. seeing replies in private chats).",
    "Izin Feishu baru telah diaktifkan. Masuk lagi untuk menggunakannya (mis. melihat balasan di chat pribadi)."
  ],
  "重新登录": [
    "Log in again",
    "Masuk lagi"
  ],
  "只授权这个定时任务、同一个对象；在“自动办的事”里可以随时收回": [
    "Only for this scheduled task and the same target; you can revoke it anytime in “Done automatically”",
    "Hanya untuk tugas terjadwal ini dan target yang sama; bisa dicabut kapan saja di “Dikerjakan otomatis”"
  ],
  "确认，以后直接办": [
    "Confirm & always do this",
    "Konfirmasi & lakukan otomatis"
  ],
  "撤销「{p0}」？": [
    "Undo “{p0}”?",
    "Batalkan “{p0}”?"
  ],
  "撤销": [
    "Undo",
    "Batalkan"
  ],
  "自动办理": [
    "Auto",
    "Otomatis"
  ],
  "已撤销": [
    "Undone",
    "Dibatalkan"
  ],
  "自动办的事": [
    "Done automatically",
    "Dikerjakan otomatis"
  ],
  "已授权直接办": [
    "Authorized to do directly",
    "Diizinkan langsung dikerjakan"
  ],
  "还没有授权。定时任务或长期任务准备的操作，确认时可以选“以后直接办”；只覆盖那个任务、那个对象。": [
    "Nothing authorized yet. When confirming an action prepared by a scheduled task or mission, choose “always do this”; it only covers that task and that target.",
    "Belum ada izin. Saat mengonfirmasi tindakan dari tugas terjadwal atau misi, pilih “lakukan otomatis”; hanya berlaku untuk tugas dan target itu."
  ],
  "收回这项授权？以后会重新先问你。": [
    "Revoke this authorization? Relay will ask you first again.",
    "Cabut izin ini? Relay akan bertanya dulu lagi."
  ],
  "收回": [
    "Revoke",
    "Cabut"
  ],
  "最近自动办的事": [
    "Recently done automatically",
    "Baru-baru ini dikerjakan otomatis"
  ],
  "最近 30 天没有自动办过事。": [
    "Nothing was done automatically in the last 30 days.",
    "Tidak ada yang dikerjakan otomatis dalam 30 hari terakhir."
  ],
  "加载中…": [
    "Loading…",
    "Memuat…"
  ],
  "查了 {count} 项": [
    "Checked {count} things",
    "Memeriksa {count} hal"
  ],
  "你交代的：": [
    "You asked: ",
    "Permintaan Anda: "
  ],
  "截止 / 复查：": [
    "Due / check: ",
    "Tenggat / cek: "
  ],
  "菜单": [
    "Menu",
    "Menu"
  ],
  "请求失败 ({p0})": [
    "Request failed ({p0})",
    "Permintaan gagal ({p0})"
  ],
  "收起": [
    "Collapse",
    "Tutup"
  ],
  "等你": [
    "Needs you",
    "Menunggu Anda"
  ],
  "等别人": [
    "Waiting on others",
    "Menunggu orang lain"
  ],
  "Relay 正在跟进": [
    "Relay is following up",
    "Relay sedang menindaklanjuti"
  ],
  "· 等别人": [
    "· Waiting on others",
    "· Menunggu orang lain"
  ],
  "· Relay 在办": [
    "· Relay is working",
    "· Dikerjakan Relay"
  ],
  "{p0}同步": [
    "Synced {p0}",
    "Disinkronkan {p0}"
  ],
  "尚未同步": [
    "Not synced yet",
    "Belum disinkronkan"
  ],
  "立即同步": [
    "Sync now",
    "Sinkronkan sekarang"
  ],
  "同步中": [
    "Syncing",
    "Menyinkronkan"
  ],
  "同步": [
    "Sync",
    "Sinkronkan"
  ],
  "现在给我一份简报": [
    "Get a briefing now",
    "Buat ringkasan sekarang"
  ],
  "生成中": [
    "Generating",
    "Membuat"
  ],
  "简报": [
    "Briefing",
    "Ringkasan"
  ],
  "没有等你处理的事": [
    "Nothing needs your attention",
    "Tidak ada yang perlu Anda tangani"
  ],
  "没有在等别人的事": [
    "Nothing waiting on others",
    "Tidak ada yang menunggu orang lain"
  ],
  "Relay 在办": [
    "Relay is working",
    "Dikerjakan Relay"
  ],
  "暂时没有": [
    "Nothing for now",
    "Belum ada"
  ],
  "模型": [
    "Model",
    "Model"
  ],
  "未配置模型": [
    "No model configured",
    "Model belum dikonfigurasi"
  ],
  "发送": [
    "Send",
    "Kirim"
  ],
  "你取消了飞书授权。": [
    "You cancelled Feishu authorization.",
    "Anda membatalkan otorisasi Feishu."
  ],
  "登录已过期，请重新发起。": [
    "Your sign-in expired. Please try again.",
    "Sesi masuk kedaluwarsa. Silakan coba lagi."
  ],
  "飞书登录失败，请稍后再试。": [
    "Feishu sign-in failed. Please try again later.",
    "Gagal masuk melalui Feishu. Silakan coba lagi nanti."
  ],
  "这个飞书账号不属于本公司，无法登录。": [
    "This Feishu account does not belong to this company.",
    "Akun Feishu ini bukan milik perusahaan ini."
  ],
  "替你留意邮件、日程和审批，该你知道的事会主动告诉你，该做的事先帮你准备好。": [
    "Stay on top of email, meetings, and approvals. Relay keeps you informed and prepares your next steps.",
    "Pantau email, jadwal, dan persetujuan. Relay memberi kabar penting dan menyiapkan langkah berikutnya."
  ],
  "登录失败。": [
    "Sign-in failed.",
    "Gagal masuk."
  ],
  "使用飞书登录": [
    "Sign in with Feishu",
    "Masuk dengan Feishu"
  ],
  "本地调试登录": [
    "Local development sign-in",
    "Masuk untuk pengembangan lokal"
  ],
  "复制": [
    "Copy",
    "Salin"
  ],
  "已复制": [
    "Copied",
    "Disalin"
  ],
  "主动告诉你": [
    "Update for you",
    "Kabar untuk Anda"
  ],
  "正在想…": [
    "Thinking…",
    "Sedang berpikir…"
  ],
  "复制全文": [
    "Copy message",
    "Salin pesan"
  ],
  "立即推进": [
    "Run now",
    "Jalankan sekarang"
  ],
  "停止这个任务？": [
    "Stop this mission?",
    "Hentikan misi ini?"
  ],
  "停止": [
    "Stop",
    "Hentikan"
  ],
  " · 正在等{p0}": [
    " · Waiting for {p0}",
    " · Menunggu {p0}"
  ],
  " · 下次 {p0} {p1}": [
    " · Next: {p0} {p1}",
    " · Berikutnya: {p0} {p1}"
  ],
  "等你确认": [
    "Needs your confirmation",
    "Menunggu konfirmasi Anda"
  ],
  "计划": [
    "Plan",
    "Rencana"
  ],
  "允许 Relay 在这个任务里自动做": [
    "Allow Relay to act automatically in this mission",
    "Izinkan Relay bertindak otomatis dalam misi ini"
  ],
  "默认所有对外操作都先问你。勾选后，这类操作在本任务里会直接执行，做完告诉你。审批始终需要你逐张处理。": [
    "External actions require your confirmation by default. Selected actions will run automatically in this mission, with an update afterward. Approvals always require individual review.",
    "Secara default, tindakan eksternal memerlukan konfirmasi Anda. Tindakan yang dipilih akan dijalankan otomatis dalam misi ini, lalu dilaporkan. Persetujuan tetap harus ditinjau satu per satu."
  ],
  "Relay 的工作笔记": [
    "Relay’s working notes",
    "Catatan kerja Relay"
  ],
  "时间线": [
    "Timeline",
    "Linimasa"
  ],
  "← 全部长期任务": [
    "← All missions",
    "← Semua misi"
  ],
  "长期任务": [
    "Missions",
    "Misi"
  ],
  "需要持续推进、要等别人回应的事，交给 Relay 在后台办。在主线里说“帮我盯着……直到……”“约齐……开会”就行。": [
    "Let Relay follow up on ongoing work in the background. In Home, ask “Follow up on… until…” or “Arrange a meeting with…”.",
    "Serahkan tindak lanjut pekerjaan kepada Relay. Di Beranda, minta “Pantau… sampai…” atau “Atur rapat dengan…”."
  ],
  "还没有长期任务。": [
    "No missions yet.",
    "Belum ada misi."
  ],
  "飞书群": [
    "Feishu group",
    "Grup Feishu"
  ],
  "定时": [
    "Scheduled",
    "Terjadwal"
  ],
  "主线": [
    "Home",
    "Beranda"
  ],
  "新对话": [
    "New chat",
    "Percakapan baru"
  ],
  "最近": [
    "Recent",
    "Terbaru"
  ],
  "删除": [
    "Delete",
    "Hapus"
  ],
  "删除这段对话？": [
    "Delete this conversation?",
    "Hapus percakapan ini?"
  ],
  "记忆": [
    "Memory",
    "Memori"
  ],
  "定时任务": [
    "Scheduled tasks",
    "Tugas terjadwal"
  ],
  "提醒设置": [
    "Settings",
    "Pengaturan"
  ],
  "业务系统接入": [
    "Integrations",
    "Integrasi"
  ],
  "退出登录": [
    "Sign out",
    "Keluar"
  ],
  "今天有哪些会？": [
    "What meetings do I have today?",
    "Apa saja rapat saya hari ini?"
  ],
  "有哪些邮件需要我回？": [
    "Which emails need my reply?",
    "Email mana yang perlu saya balas?"
  ],
  "我有什么待审批的？": [
    "What approvals are waiting for me?",
    "Persetujuan apa yang menunggu saya?"
  ],
  "帮我搜一下报价相关的文档": [
    "Find documents about quotations",
    "Cari dokumen terkait penawaran harga"
  ],
  "发送失败": [
    "Send failed",
    "Gagal mengirim"
  ],
  "我会替你留意邮件、日程、审批和考勤，有需要你知道或决定的事会直接在这里告诉你。也可以随时让我帮你做事。": [
    "I’ll keep an eye on email, meetings, approvals, and attendance, and let you know here when something needs your attention. You can ask me for help anytime.",
    "Saya akan memantau email, jadwal, persetujuan, dan kehadiran, lalu memberi tahu di sini jika ada yang perlu Anda perhatikan. Anda juga bisa meminta bantuan kapan saja."
  ],
  "想让我帮你做什么？": [
    "What can I help you with?",
    "Apa yang bisa saya bantu?"
  ],
  "回复 Relay，或让它帮你做点什么…": [
    "Reply to Relay or ask for help…",
    "Balas Relay atau minta bantuan…"
  ],
  "给 Relay 发消息…": [
    "Message Relay…",
    "Kirim pesan ke Relay…"
  ],
  "发邮件、回复会议邀请等操作都会先让你确认": [
    "You’ll be asked to confirm before sending email or responding to invitations",
    "Konfirmasi Anda akan diminta sebelum mengirim email atau membalas undangan"
  ],
  "操作失败": [
    "Action failed",
    "Tindakan gagal"
  ],
  "邮件": [
    "Email",
    "Email"
  ],
  "起草中…": [
    "Drafting…",
    "Membuat draf…"
  ],
  "起草回复": [
    "Draft reply",
    "Buat draf balasan"
  ],
  "紧急": [
    "Urgent",
    "Mendesak"
  ],
  "等你回复": [
    "Needs your reply",
    "Menunggu balasan Anda"
  ],
  "收件人": [
    "To",
    "Kepada"
  ],
  "抄送": [
    "Cc",
    "Tembusan"
  ],
  "主题": [
    "Subject",
    "Subjek"
  ],
  "起草时参考了：": [
    "Draft references: ",
    "Referensi draf: "
  ],
  "发送中…": [
    "Sending…",
    "Mengirim…"
  ],
  "确认发送": [
    "Confirm and send",
    "Konfirmasi dan kirim"
  ],
  "保存修改": [
    "Save changes",
    "Simpan perubahan"
  ],
  "不用了": [
    "Not needed",
    "Tidak perlu"
  ],
  "待你确认": [
    "Awaiting confirmation",
    "Menunggu konfirmasi"
  ],
  "已发送": [
    "Sent",
    "Terkirim"
  ],
  "已取消": [
    "Cancelled",
    "Dibatalkan"
  ],
  "回复草稿": [
    "Reply draft",
    "Draf balasan"
  ],
  "已接受": [
    "Accepted",
    "Diterima"
  ],
  "待定": [
    "Tentative",
    "Tentatif"
  ],
  "已拒绝": [
    "Declined",
    "Ditolak"
  ],
  "未回复": [
    "No response",
    "Belum dibalas"
  ],
  "日历": [
    "Calendar",
    "Kalender"
  ],
  "接受": [
    "Accept",
    "Terima"
  ],
  "拒绝": [
    "Decline",
    "Tolak"
  ],
  "确认：": [
    "Confirm: ",
    "Konfirmasi: "
  ],
  "取消": [
    "Cancel",
    "Batal"
  ],
  "加入会议": [
    "Join meeting",
    "Gabung rapat"
  ],
  "在飞书打开": [
    "Open in Feishu",
    "Buka di Feishu"
  ],
  "全天": [
    "All day",
    "Sepanjang hari"
  ],
  "组织者": [
    "Organizer",
    "Penyelenggara"
  ],
  "审批": [
    "Approvals",
    "Persetujuan"
  ],
  "待你审批": [
    "Awaiting your approval",
    "Menunggu persetujuan Anda"
  ],
  "去审批": [
    "Review approval",
    "Tinjau persetujuan"
  ],
  "考勤": [
    "Attendance",
    "Kehadiran"
  ],
  "群消息": [
    "Group messages",
    "Pesan grup"
  ],
  "提醒": [
    "Reminder",
    "Pengingat"
  ],
  "去处理": [
    "Take action",
    "Tangani"
  ],
  "飞书文档": [
    "Feishu Docs",
    "Dokumen Feishu"
  ],
  "等你处理": [
    "Needs your attention",
    "Perlu Anda tangani"
  ],
  "会议邀请": [
    "Meeting invitation",
    "Undangan rapat"
  ],
  "等你审批": [
    "Needs your approval",
    "Perlu persetujuan Anda"
  ],
  "群里@你": [
    "Group mentions",
    "Sebutan di grup"
  ],
  "有人找你办事": [
    "Request for you",
    "Permintaan untuk Anda"
  ],
  "业务系统": [
    "Business system",
    "Sistem bisnis"
  ],
  "等对方回复": [
    "Waiting for a reply",
    "Menunggu balasan"
  ],
  "去飞书审批": [
    "Review in Feishu",
    "Tinjau di Feishu"
  ],
  "批准": [
    "Approve",
    "Setujui"
  ],
  "驳回「{p0}」？": [
    "Reject “{p0}”?",
    "Tolak “{p0}”?"
  ],
  "驳回": [
    "Reject",
    "Tolak"
  ],
  "在飞书查看": [
    "View in Feishu",
    "Lihat di Feishu"
  ],
  "我已处理": [
    "Mark as done",
    "Tandai selesai"
  ],
  "不用跟了": [
    "Stop following up",
    "Hentikan tindak lanjut"
  ],
  "→ 需要你：": [
    "→ Your next step: ",
    "→ Langkah Anda: "
  ],
  "申请内容": [
    "Request details",
    "Detail permintaan"
  ],
  "Relay 已起草回复，展开确认": [
    "Relay has drafted a reply. Expand to review.",
    "Relay telah membuat draf balasan. Buka untuk meninjaunya."
  ],
  "邮件草稿": [
    "Email draft",
    "Draf email"
  ],
  "已执行": [
    "Completed",
    "Selesai"
  ],
  "失败": [
    "Failed",
    "Gagal"
  ],
  "待确认操作": [
    "Action to confirm",
    "Tindakan untuk dikonfirmasi"
  ],
  "确认执行": [
    "Confirm action",
    "Konfirmasi tindakan"
  ],
  "对象：": [
    "For: ",
    "Untuk: "
  ],
  "时间：": [
    "Time: ",
    "Waktu: "
  ],
  "截止：": [
    "Due: ",
    "Tenggat: "
  ],
  "单元格": [
    "Cell",
    "Sel"
  ],
  "原值": [
    "Previous value",
    "Nilai sebelumnya"
  ],
  "新值": [
    "New value",
    "Nilai baru"
  ],
  "（空）": [
    "(empty)",
    "(kosong)"
  ],
  "注意：": [
    "Note: ",
    "Catatan: "
  ],
  "推进中": [
    "In progress",
    "Sedang berjalan"
  ],
  "在等对方": [
    "Waiting on others",
    "Menunggu orang lain"
  ],
  "在等你回答": [
    "Waiting for your answer",
    "Menunggu jawaban Anda"
  ],
  "已完成": [
    "Done",
    "Selesai"
  ],
  "没办成": [
    "Unsuccessful",
    "Tidak berhasil"
  ],
  "查看进展": [
    "View progress",
    "Lihat perkembangan"
  ],
  " · 在等{p0}": [
    " · Waiting for {p0}",
    " · Menunggu {p0}"
  ],
  "→ 需要你回答：": [
    "→ Your answer is needed: ",
    "→ Perlu jawaban Anda: "
  ],
  "你的回答": [
    "Your answer",
    "Jawaban Anda"
  ],
  "回复": [
    "Reply",
    "Balas"
  ],
  "关闭": [
    "Close",
    "Tutup"
  ],
  "关于你": [
    "About you",
    "Tentang Anda"
  ],
  "发生过的事": [
    "Past events",
    "Peristiwa sebelumnya"
  ],
  "Relay 记住的这些会用在之后的每次判断和对话里。不对的可以直接删掉。": [
    "Relay uses these memories in future decisions and conversations. Delete anything that’s incorrect.",
    "Relay menggunakan memori ini dalam keputusan dan percakapan berikutnya. Hapus yang tidak benar."
  ],
  "还没有记忆。聊着聊着就会有了。": [
    "No memories yet. They’ll build up as you chat.",
    "Belum ada memori. Memori akan bertambah saat Anda mengobrol."
  ],
  "在对话里说“每周一早上 9 点提醒我写周报”就能创建。": [
    "To create a task, say “Remind me to write my weekly report every Monday at 9 AM”.",
    "Untuk membuat tugas, katakan “Ingatkan saya menulis laporan mingguan setiap Senin pukul 09.00”."
  ],
  "还没有定时任务。": [
    "No scheduled tasks yet.",
    "Belum ada tugas terjadwal."
  ],
  "周期 {p0}": [
    "Schedule: {p0}",
    "Jadwal: {p0}"
  ],
  "一次性": [
    "One time",
    "Sekali saja"
  ],
  " · 已结束": [
    " · Finished",
    " · Selesai"
  ],
  "群消息里@我": [
    "Mentions in group chats",
    "Sebutan di percakapan grup"
  ],
  "主动提醒": [
    "Proactive reminders",
    "Pengingat otomatis"
  ],
  "关闭后 Relay 只在你找它时回应": [
    "When off, Relay only responds when you ask",
    "Jika dimatikan, Relay hanya merespons saat Anda meminta"
  ],
  "留意哪些事": [
    "What to watch",
    "Hal yang dipantau"
  ],
  "语言": [
    "Language",
    "Bahasa"
  ],
  "Relay 用什么语言和你说话": [
    "Relay’s response language",
    "Bahasa balasan Relay"
  ],
  "跟随我的消息自动识别": [
    "Detect from my messages",
    "Deteksi dari pesan saya"
  ],
  "简体中文": [
    "简体中文",
    "简体中文"
  ],
  "主动提醒、简报和飞书卡片用这个语言。替你写给别人的邮件和消息，会用对方的语言。": [
    "Controls Relay’s reminders, briefings, and Feishu cards. Emails and messages drafted for others use the recipient’s language.",
    "Mengatur bahasa pengingat, ringkasan, dan kartu Feishu. Email serta pesan untuk orang lain menggunakan bahasa penerima."
  ],
  "节奏": [
    "Timing",
    "Waktu"
  ],
  "工作日自动发简报": [
    "Automatic weekday briefing",
    "Ringkasan otomatis pada hari kerja"
  ],
  "免打扰": [
    "Quiet hours",
    "Waktu tenang"
  ],
  "至": [
    "to",
    "hingga"
  ],
  "会前准备提前（分钟）": [
    "Meeting preparation lead time (minutes)",
    "Persiapan sebelum rapat (menit)"
  ],
  "每小时最多打扰": [
    "Maximum reminders per hour",
    "Maksimum pengingat per jam"
  ],
  "已保存": [
    "Saved",
    "Tersimpan"
  ],
  "保存": [
    "Save",
    "Simpan"
  ],
  "Relay 记住的事": [
    "Relay’s memories",
    "Memori Relay"
  ],
  "已送达": [
    "Delivered",
    "Tersampaikan"
  ],
  "部分送达": [
    "Partially delivered",
    "Sebagian tersampaikan"
  ],
  "没找到收件人": [
    "Recipient not found",
    "Penerima tidak ditemukan"
  ],
  "已标记解决": [
    "Marked resolved",
    "Ditandai selesai"
  ],
  "接入信息": [
    "Connection details",
    "Detail koneksi"
  ],
  "推送地址": [
    "Webhook URL",
    "URL webhook"
  ],
  "签名密钥": [
    "Signing secret",
    "Kunci penandatanganan"
  ],
  "隐藏密钥": [
    "Hide secret",
    "Sembunyikan kunci"
  ],
  "显示密钥": [
    "Show secret",
    "Tampilkan kunci"
  ],
  "换一个新密钥？旧密钥会立即失效。": [
    "Generate a new secret? The old one will stop working immediately.",
    "Buat kunci baru? Kunci lama akan langsung tidak berlaku."
  ],
  "更换密钥": [
    "Rotate secret",
    "Ganti kunci"
  ],
  "删除「{p0}」？": [
    "Delete “{p0}”?",
    "Hapus “{p0}”?"
  ],
  "签名方式（Python 示例）": [
    "Signing example (Python)",
    "Contoh penandatanganan (Python)"
  ],
  "最近收到的事件": [
    "Recent events",
    "Peristiwa terbaru"
  ],
  "还没有收到事件": [
    "No events received yet",
    "Belum ada peristiwa diterima"
  ],
  "业务系统（TMS、WMS、CRM……）有需要人处理的事时，推给 Relay：Relay 会通知到具体的人、放进他的跟进看板， 业务系统推送“已解决”时自动关闭。同一归并键（如订单号）的事件会更新同一件事。": [
    "Send events from business systems (TMS, WMS, CRM…) to Relay. Relay notifies the right person and adds a follow-up. A resolved event closes it automatically. Events with the same group key, such as an order number, update the same item.",
    "Kirim peristiwa dari sistem bisnis (TMS, WMS, CRM…) ke Relay. Relay memberi tahu orang yang tepat dan menambahkan tindak lanjut. Peristiwa berstatus resolved menutupnya otomatis. Kunci grup yang sama, seperti nomor pesanan, memperbarui item yang sama."
  ],
  "登记一个业务系统": [
    "Register a business system",
    "Daftarkan sistem bisnis"
  ],
  "名称": [
    "Name",
    "Nama"
  ],
  "例如 TMS": [
    "For example, TMS",
    "Misalnya, TMS"
  ],
  "说明": [
    "Description",
    "Deskripsi"
  ],
  "推送哪些事件": [
    "Events this system sends",
    "Peristiwa yang dikirim sistem ini"
  ],
  "生成推送地址和密钥": [
    "Generate URL and secret",
    "Buat URL dan kunci"
  ],
  "已接入": [
    "Connected systems",
    "Sistem terhubung"
  ],
  "还没有接入业务系统。": [
    "No business systems connected yet.",
    "Belum ada sistem bisnis terhubung."
  ],
  "推送格式": [
    "Event format",
    "Format peristiwa"
  ],
  "priority：urgent 紧急（免打扰时段也会通知）、normal、low（只进简报）。status 传 resolved 时关闭对应的事。 recipients 支持 email、open_id 或名字。": [
    "priority: urgent (including quiet hours), normal, or low (briefings only). Set status to resolved to close the item. recipients accepts email, open_id, or name.",
    "priority: urgent (termasuk saat waktu tenang), normal, atau low (hanya ringkasan). Gunakan status resolved untuk menutup item. recipients menerima email, open_id, atau nama."
  ],
  "查看了日历": [
    "Checked calendar",
    "Memeriksa kalender"
  ],
  "正在查看日历": [
    "Checking calendar",
    "Memeriksa kalender"
  ],
  "搜了邮箱": [
    "Searched email",
    "Mencari email"
  ],
  "正在搜邮箱": [
    "Searching email",
    "Mencari email"
  ],
  "看了邮件文件夹": [
    "Checked mail folders",
    "Memeriksa folder email"
  ],
  "正在看邮件文件夹": [
    "Checking mail folders",
    "Memeriksa folder email"
  ],
  "读了邮件": [
    "Read email",
    "Membaca email"
  ],
  "正在读邮件": [
    "Reading email",
    "Membaca email"
  ],
  "起草了回复": [
    "Drafted reply",
    "Membuat draf balasan"
  ],
  "正在起草回复": [
    "Drafting reply",
    "Membuat draf balasan"
  ],
  "修改了草稿": [
    "Revised draft",
    "Memperbarui draf"
  ],
  "正在修改草稿": [
    "Revising draft",
    "Memperbarui draf"
  ],
  "执行了操作": [
    "Completed action",
    "Menyelesaikan tindakan"
  ],
  "正在执行": [
    "Running action",
    "Menjalankan tindakan"
  ],
  "准备了会议回复": [
    "Prepared meeting response",
    "Menyiapkan balasan rapat"
  ],
  "正在准备会议回复": [
    "Preparing meeting response",
    "Menyiapkan balasan rapat"
  ],
  "查看了审批": [
    "Checked approvals",
    "Memeriksa persetujuan"
  ],
  "正在查看审批": [
    "Checking approvals",
    "Memeriksa persetujuan"
  ],
  "查看了考勤": [
    "Checked attendance",
    "Memeriksa kehadiran"
  ],
  "正在查看考勤": [
    "Checking attendance",
    "Memeriksa kehadiran"
  ],
  "搜索了文档": [
    "Searched documents",
    "Mencari dokumen"
  ],
  "正在搜索文档": [
    "Searching documents",
    "Mencari dokumen"
  ],
  "读了文档": [
    "Read document",
    "Membaca dokumen"
  ],
  "正在读文档": [
    "Reading document",
    "Membaca dokumen"
  ],
  "记住了一件事": [
    "Saved a memory",
    "Menyimpan memori"
  ],
  "正在记下来": [
    "Saving a memory",
    "Menyimpan memori"
  ],
  "删除了一条记忆": [
    "Deleted a memory",
    "Menghapus memori"
  ],
  "正在删除记忆": [
    "Deleting a memory",
    "Menghapus memori"
  ],
  "回想了一下": [
    "Recalled memories",
    "Mengingat kembali"
  ],
  "正在回想": [
    "Recalling memories",
    "Mengingat kembali"
  ],
  "创建了定时任务": [
    "Created scheduled task",
    "Membuat tugas terjadwal"
  ],
  "正在创建定时任务": [
    "Creating scheduled task",
    "Membuat tugas terjadwal"
  ],
  "查看了定时任务": [
    "Checked scheduled tasks",
    "Memeriksa tugas terjadwal"
  ],
  "正在查看定时任务": [
    "Checking scheduled tasks",
    "Memeriksa tugas terjadwal"
  ],
  "删除了定时任务": [
    "Deleted scheduled task",
    "Menghapus tugas terjadwal"
  ],
  "正在删除定时任务": [
    "Deleting scheduled task",
    "Menghapus tugas terjadwal"
  ],
  "接下了长期任务": [
    "Started mission",
    "Memulai misi"
  ],
  "正在接下长期任务": [
    "Starting mission",
    "Memulai misi"
  ],
  "查看了长期任务": [
    "Checked missions",
    "Memeriksa misi"
  ],
  "正在查看长期任务": [
    "Checking missions",
    "Memeriksa misi"
  ],
  "转告了长期任务": [
    "Updated mission",
    "Memperbarui misi"
  ],
  "正在转告长期任务": [
    "Updating mission",
    "Memperbarui misi"
  ],
  "停止了长期任务": [
    "Stopped mission",
    "Menghentikan misi"
  ],
  "正在停止长期任务": [
    "Stopping mission",
    "Menghentikan misi"
  ],
  "找了同事": [
    "Found colleague",
    "Menemukan rekan kerja"
  ],
  "正在找同事": [
    "Finding colleague",
    "Mencari rekan kerja"
  ],
  "查了大家的空闲时间": [
    "Checked availability",
    "Memeriksa waktu luang"
  ],
  "正在查大家的空闲时间": [
    "Checking availability",
    "Memeriksa waktu luang"
  ],
  "准备了一条消息": [
    "Prepared message",
    "Menyiapkan pesan"
  ],
  "正在准备消息": [
    "Preparing message",
    "Menyiapkan pesan"
  ],
  "准备了飞书任务": [
    "Prepared Feishu task",
    "Menyiapkan tugas Feishu"
  ],
  "正在准备飞书任务": [
    "Preparing Feishu task",
    "Menyiapkan tugas Feishu"
  ],
  "准备了会议邀请": [
    "Prepared invitation",
    "Menyiapkan undangan"
  ],
  "正在准备会议邀请": [
    "Preparing invitation",
    "Menyiapkan undangan"
  ],
  "查看了跟进事项": [
    "Checked follow-ups",
    "Memeriksa tindak lanjut"
  ],
  "正在查看跟进事项": [
    "Checking follow-ups",
    "Memeriksa tindak lanjut"
  ],
  "结束了一件跟进": [
    "Closed follow-up",
    "Menutup tindak lanjut"
  ],
  "正在结束跟进": [
    "Closing follow-up",
    "Menutup tindak lanjut"
  ],
  "读了审批单": [
    "Read approval request",
    "Membaca permintaan persetujuan"
  ],
  "正在读审批单": [
    "Reading approval request",
    "Membaca permintaan persetujuan"
  ],
  "准备了审批决定": [
    "Prepared approval decision",
    "Menyiapkan keputusan persetujuan"
  ],
  "正在准备审批决定": [
    "Preparing approval decision",
    "Menyiapkan keputusan persetujuan"
  ],
  "查了参会人的回复": [
    "Checked attendee responses",
    "Memeriksa balasan peserta"
  ],
  "正在查参会人的回复": [
    "Checking attendee responses",
    "Memeriksa balasan peserta"
  ],
  "查了组织架构": [
    "Checked organization",
    "Memeriksa struktur organisasi"
  ],
  "正在查组织架构": [
    "Checking organization",
    "Memeriksa struktur organisasi"
  ],
  "找了群": [
    "Found groups",
    "Menemukan grup"
  ],
  "正在找群": [
    "Finding groups",
    "Mencari grup"
  ],
  "读了群消息": [
    "Read group messages",
    "Membaca pesan grup"
  ],
  "正在读群消息": [
    "Reading group messages",
    "Membaca pesan grup"
  ],
  "查了部门成员": [
    "Checked department members",
    "Memeriksa anggota departemen"
  ],
  "正在查部门成员": [
    "Checking department members",
    "Memeriksa anggota departemen"
  ],
  "查了同事资料": [
    "Checked colleague profile",
    "Memeriksa profil rekan kerja"
  ],
  "正在查同事资料": [
    "Checking colleague profile",
    "Memeriksa profil rekan kerja"
  ],
  "准备了改期": [
    "Prepared reschedule",
    "Menyiapkan perubahan jadwal"
  ],
  "正在准备改期": [
    "Preparing reschedule",
    "Menyiapkan perubahan jadwal"
  ],
  "准备了取消会议": [
    "Prepared cancellation",
    "Menyiapkan pembatalan rapat"
  ],
  "正在准备取消会议": [
    "Preparing cancellation",
    "Menyiapkan pembatalan rapat"
  ],
  "准备了加参会人": [
    "Prepared attendee additions",
    "Menyiapkan penambahan peserta"
  ],
  "正在准备加参会人": [
    "Preparing attendee additions",
    "Menyiapkan penambahan peserta"
  ],
  "以后这一类（同一种审批 / 同一个发件人 / 同一个群）只放进早上的简报，可在提醒设置里改": [
    "From now on, items like this (same approval type / sender / group) only go into the morning brief. You can change this in Settings.",
    "Mulai sekarang, hal seperti ini (jenis persetujuan / pengirim / grup yang sama) hanya masuk ringkasan pagi. Bisa diubah di Pengaturan."
  ],
  "少提醒这类": [
    "Fewer like this",
    "Kurangi yang seperti ini"
  ],
  "按你的设置，这类不提醒，只在这里跟踪": [
    "Per your settings, items like this aren't notified — only tracked here",
    "Sesuai pengaturan Anda, hal seperti ini tidak diberitahukan — hanya dilacak di sini"
  ],
  "按你的设置，这类放进早上的简报再告诉你": [
    "Per your settings, this will be in your morning brief",
    "Sesuai pengaturan Anda, ini akan ada di ringkasan pagi"
  ],
  "不急，Relay 会在下次汇总时告诉你": [
    "Not urgent — Relay will include it in the next digest",
    "Tidak mendesak — Relay akan menyertakannya di ringkasan berikutnya"
  ],
  "立刻告诉我": [
    "Tell me right away",
    "Beri tahu segera"
  ],
  "攒着一起说": [
    "Bundle into digests",
    "Kumpulkan di ringkasan"
  ],
  "只放进早上简报": [
    "Morning brief only",
    "Hanya di ringkasan pagi"
  ],
  "不提醒，只在看板里跟踪": [
    "Don't notify, just track on the board",
    "Jangan beri tahu, cukup lacak di papan"
  ],
  "聊天里的事": [
    "Chat requests",
    "Permintaan di chat"
  ],
  "在等别人的事": [
    "Things you're waiting on",
    "Hal yang Anda tunggu"
  ],
  "业务系统通知": [
    "System notifications",
    "Notifikasi sistem"
  ],
  "所有事": [
    "Everything",
    "Semua hal"
  ],
  "相关的人：{name}": [
    "Person: {name}",
    "Orang: {name}"
  ],
  "群：{name}": [
    "Group: {name}",
    "Grup: {name}"
  ],
  "提醒规则": [
    "Notification rules",
    "Aturan pemberitahuan"
  ],
  "你说过的提醒偏好，Relay 每次通知前都会照做。在对话里说“请假审批不用提醒我”“Budi 的事随时告诉我”，或在事项上点“少提醒这类”，都会出现在这里。": [
    "Your notification preferences — Relay applies them before every notification. Say things like “Don't notify me about leave approvals” or “Always tell me about Budi's requests” in chat, or tap “Fewer like this” on an item, and they show up here.",
    "Preferensi pemberitahuan Anda — Relay menerapkannya sebelum setiap pemberitahuan. Katakan di chat misalnya “Persetujuan cuti tidak perlu diberitahukan” atau “Selalu beri tahu soal Budi”, atau ketuk “Kurangi yang seperti ini” pada suatu hal; aturannya muncul di sini."
  ],
  "还没有规则。": [
    "No rules yet.",
    "Belum ada aturan."
  ],
  "已用在 {n} 件事上": [
    "applied to {n} items",
    "diterapkan pada {n} hal"
  ],
  "提醒方式": [
    "How to notify",
    "Cara memberi tahu"
  ],
  "不急的事汇总时间": [
    "Digest times for non-urgent items",
    "Waktu ringkasan untuk hal tidak mendesak"
  ],
  "加一个时间": [
    "Add a time",
    "Tambah waktu"
  ],
  "紧急的事和你上级找你的事随时告诉你，不受次数限制；今天要你处理的事马上告诉你，但每小时有上限，超出的稍后再说；其余的攒到汇总时间一起说，早上的简报也算一次。免打扰时段只说紧急的。": [
    "Urgent items and anything from your managers come through right away, with no limit. Things due today are sent right away too, up to the hourly limit — any beyond that follow shortly. Everything else is bundled into the digests (the morning brief counts as one). During quiet hours, only urgent items come through.",
    "Hal mendesak dan apa pun dari atasan Anda langsung disampaikan, tanpa batas. Hal yang harus diselesaikan hari ini juga langsung disampaikan, sampai batas per jam — sisanya menyusul sebentar lagi. Sisanya dikumpulkan di waktu ringkasan (ringkasan pagi juga termasuk). Saat waktu tenang, hanya hal mendesak yang disampaikan."
  ],
  "等你确认的候选": [
    "Suggestions to confirm",
    "Saran untuk dikonfirmasi"
  ],
  "从你以前说过的话整理出来，确认前不会生效。": [
    "Drawn from what you've said before. They don't take effect until you confirm.",
    "Disusun dari yang pernah Anda katakan. Tidak berlaku sebelum Anda konfirmasi."
  ],
  "依据：": [
    "Based on: ",
    "Berdasarkan: "
  ],
  "启用": [
    "Turn on",
    "Aktifkan"
  ],
  "不用": [
    "No thanks",
    "Tidak perlu"
  ],
  "紧急的事（例如运营事故、客户或上级催办）即使命中“少提醒”的规则，也会照样马上告诉你。": [
    "Urgent items (such as an operational incident, or a customer or manager chasing you) still come through right away, even if a “fewer reminders” rule matches.",
    "Hal mendesak (misalnya insiden operasional, atau pelanggan/atasan yang menagih) tetap langsung disampaikan meskipun cocok dengan aturan “kurangi pemberitahuan”."
  ],
  "你发的邮件": [
    "Your email",
    "Email Anda"
  ],
  "附件": [
    "Attachment",
    "Lampiran"
  ],
  "审批单": [
    "Approval form",
    "Formulir persetujuan"
  ],
  "聊天": [
    "Chat",
    "Chat"
  ],
  "会议": [
    "Meeting",
    "Rapat"
  ],
  "之前的事": [
    "Earlier item",
    "Hal sebelumnya"
  ],
  "关联依据：": [
    "Why it's linked: ",
    "Alasan terkait: "
  ],
  "查看原文": [
    "View original",
    "Lihat asli"
  ],
  "正在读取…": [
    "Loading…",
    "Memuat…"
  ],
  "内容较长，只显示了前面一部分。": [
    "This is long; only the beginning is shown.",
    "Isinya panjang; hanya bagian awal yang ditampilkan."
  ],
  "相关材料": [
    "Related materials",
    "Materi terkait"
  ],
  "正在查找…": [
    "Looking…",
    "Mencari…"
  ],
  "没有找到相关材料。": [
    "No related materials found.",
    "Tidak ada materi terkait."
  ],
  "只是同一个人，未必和这件事有关：": [
    "Same person only — may not be about this item:",
    "Hanya orang yang sama — belum tentu terkait hal ini:"
  ],
  "这些材料是按规则关联的（同一邮件线程、链接、提到同样的内容……），是否真的相关请以原文为准。": [
    "These materials are linked by rules (same email thread, links, mentions of the same things…). Check the original to confirm they're really relevant.",
    "Materi ini dikaitkan berdasarkan aturan (utas email yang sama, tautan, menyebut hal yang sama…). Periksa aslinya untuk memastikan benar-benar terkait."
  ],
  "飞书任务": [
    "Feishu tasks",
    "Tugas Feishu"
  ],
  "飞书任务里派给我的事": [
    "Feishu tasks assigned to me",
    "Tugas Feishu yang ditugaskan ke saya"
  ]
};
