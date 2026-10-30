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
  ],
  "验收清单": [
    "Acceptance checklist",
    "Daftar penerimaan"
  ],
  "做到这几条才算办成。Relay 每标记一条都要附上证据，结束前还会独立核对一遍；条目只有你能改。": [
    "Done only when every item is met. Relay must attach evidence for each one, and an independent check runs before it closes the task. Only you can change the items.",
    "Selesai hanya jika semua butir terpenuhi. Relay wajib melampirkan bukti untuk tiap butir, dan ada pemeriksaan independen sebelum tugas ditutup. Hanya Anda yang bisa mengubah butirnya."
  ],
  "验收清单，每行一条": [
    "Acceptance checklist, one item per line",
    "Daftar penerimaan, satu butir per baris"
  ],
  "这个任务还没有验收清单，以你交代的原话为准。": [
    "This task has no checklist yet; your original request is the standard.",
    "Tugas ini belum punya daftar penerimaan; permintaan asli Anda yang jadi acuan."
  ],
  "修改": [
    "Edit",
    "Ubah"
  ],
  "帮 Relay 变聪明": [
    "Help Relay get smarter",
    "Bantu Relay jadi lebih pintar"
  ],
  "新方式整理的承诺": [
    "New approach: commitments",
    "Cara baru: komitmen"
  ],
  "现在系统的事项": [
    "Current system: items",
    "Sistem saat ini: item"
  ],
  "两边都漏掉的": [
    "Missed by both",
    "Terlewat oleh keduanya"
  ],
  "你确实欠别人、或在等别人的事，但上面两边都没有。每次写一件。": [
    "Things you really owe someone or are waiting on, but neither side caught. One per entry.",
    "Hal yang benar-benar Anda utangkan atau tunggu, tapi tidak tertangkap di kedua sisi. Satu per entri."
  ],
  "例如：等 Hendri 发 9 月运单明细": [
    "e.g. Waiting for Hendri to send the September waybill details",
    "mis. Menunggu Hendri mengirim rincian resi September"
  ],
  "提交": [
    "Submit",
    "Kirim"
  ],
  "我欠": [
    "I owe",
    "Saya berutang"
  ],
  "对方欠我": [
    "Owed to me",
    "Mereka berutang ke saya"
  ],
  "截止": [
    "due",
    "tenggat"
  ],
  "这件事的材料（{count} 条）": [
    "Materials ({count})",
    "Materi ({count})"
  ],
  "未完成": [
    "Not done",
    "Belum selesai"
  ],
  "已办完": [
    "Done",
    "Selesai"
  ],
  "不用办了": [
    "No longer needed",
    "Tidak perlu lagi"
  ],
  "5 天没动静": [
    "Quiet for 5 days",
    "Diam 5 hari"
  ],
  "已结束": [
    "Closed",
    "Ditutup"
  ],
  "未结": [
    "Open",
    "Terbuka"
  ],
  "保存失败，请重试": [
    "Couldn't save — please try again",
    "Gagal menyimpan — coba lagi"
  ],
  "新旧链路评估": [
    "Old vs new pipeline",
    "Evaluasi alur lama vs baru"
  ],
  "用户": [
    "User",
    "Pengguna"
  ],
  "新方式": [
    "New approach",
    "Cara baru"
  ],
  "现在的系统": [
    "Current system",
    "Sistem saat ini"
  ],
  "漏掉的": [
    "Missed",
    "Terlewat"
  ],
  "已整理到": [
    "Updated",
    "Diperbarui"
  ],
  "合计": [
    "Total",
    "Total"
  ],
  "整理中": [
    "Processing",
    "Diproses"
  ],
  "对": [
    "Right",
    "Benar"
  ],
  "不对": [
    "Wrong",
    "Salah"
  ],
  "哪里不对？（可选）": [
    "What's wrong? (optional)",
    "Apa yang salah? (opsional)"
  ],
  "不是我的事": [
    "Not mine",
    "Bukan urusan saya"
  ],
  "其实已经办完了": [
    "Already done",
    "Sudah selesai"
  ],
  "其实还没办完": [
    "Not done yet",
    "Belum selesai"
  ],
  "重复了": [
    "Duplicate",
    "Duplikat"
  ],
  "很久以前的事": [
    "From long ago",
    "Sudah lama sekali"
  ],
  "内容不对": [
    "Details wrong",
    "Isinya salah"
  ],
  "补充一句（可选）": [
    "Add a note (optional)",
    "Tambahkan catatan (opsional)"
  ],
  "时间范围": [
    "Time range",
    "Rentang waktu"
  ],
  "最近 {count} 天": [
    "Last {count} days",
    "{count} hari terakhir"
  ],
  "我们在试一种新方式：把同一件事的邮件、聊天、审批放在一起，判断“谁欠谁什么、办完没有”。它只在后台计算，不会给你发提醒。觉得对就点 👍，不对点 👎，愿意的话说一下哪里不对。只有你自己看得到。": [
    "We're trying a new approach: emails, chats and approvals about the same matter are kept together to work out who owes whom what, and whether it's done. It only runs in the background and won't send you reminders. Tap 👍 if it's right, 👎 if not — and say what's wrong if you like. Only you can see this.",
    "Kami sedang mencoba cara baru: email, chat, dan persetujuan tentang hal yang sama dikumpulkan untuk melihat siapa berutang apa kepada siapa, dan apakah sudah selesai. Hanya berjalan di latar belakang dan tidak mengirim pengingat. Ketuk 👍 jika benar, 👎 jika tidak — dan sebutkan yang salah jika mau. Hanya Anda yang dapat melihat ini."
  ],
  "开始": [
    "Start",
    "Mulai"
  ],
  "这段时间没有事项。": [
    "No items in this period.",
    "Tidak ada item dalam periode ini."
  ],
  "没说原因": [
    "No reason given",
    "Tanpa alasan"
  ],
  "每格是 👍 的占比（反馈数），以及最常见的 👎 原因。内容只有本人看得到。": [
    "Each cell shows the 👍 share (feedback count) and the most common 👎 reasons. Only each person can see their own content.",
    "Setiap sel menunjukkan porsi 👍 (jumlah umpan balik) dan alasan 👎 yang paling sering. Isi hanya bisa dilihat pemiliknya."
  ],
  "整理多久的事？": [
    "How far back should Relay look?",
    "Seberapa jauh ke belakang?"
  ],
  "开始后范围就定下来了；整理完之后有新消息会自动更新。": [
    "The range is fixed once you start; after that, new messages are added automatically.",
    "Rentang tidak bisa diubah setelah dimulai; setelah itu pesan baru ditambahkan otomatis."
  ],
  "正在开始…": [
    "Starting…",
    "Memulai…"
  ],
  "整理范围：最近 {count} 天": [
    "Range: last {count} days",
    "Rentang: {count} hari terakhir"
  ],
  "排队中，马上开始…": [
    "Queued — starting shortly…",
    "Dalam antrean — segera dimulai…"
  ],
  "正在整理 {percent}%，已整理出的结果可以先看": [
    "Organising {percent}% — you can review what's ready so far",
    "Sedang dirapikan {percent}% — hasil yang sudah ada bisa dilihat"
  ],
  "已整理完，有新消息会自动更新（最近一次 {time}）": [
    "Done — new messages are added automatically (last update {time})",
    "Selesai — pesan baru ditambahkan otomatis (terakhir {time})"
  ],
  "正在整理，结果会陆续出现在这里。": [
    "Organising — results will appear here as they're ready.",
    "Sedang dirapikan — hasil akan muncul di sini."
  ],
  "这段时间没有整理出要跟进的事。": [
    "Nothing to follow up on in this period.",
    "Tidak ada yang perlu ditindaklanjuti dalam periode ini."
  ],
  "已处理": [
    "Done",
    "Sudah ditangani"
  ],
  "为什么不用跟了？": [
    "Why stop tracking?",
    "Kenapa tidak perlu dipantau?"
  ],
  "提醒前就处理了": [
    "Already handled before",
    "Sudah ditangani sebelumnya"
  ],
  "不归我管": [
    "Not mine",
    "Bukan urusan saya"
  ],
  "不值得提醒": [
    "Not worth a reminder",
    "Tidak perlu diingatkan"
  ],
  "这类以后少提醒": [
    "Fewer like this",
    "Kurangi yang seperti ini"
  ],
  "返回": [
    "Back",
    "Kembali"
  ],
  "待处理": [
    "To do",
    "Perlu ditangani"
  ],
  "进展": [
    "Progress",
    "Perkembangan"
  ],
  "对话": [
    "Chat",
    "Obrolan"
  ],
  "新旧链路对比": [
    "Pipeline comparison",
    "Perbandingan alur"
  ],
  "主要入口": [
    "Main sections",
    "Bagian utama"
  ],
  "关于 #{id}《{title}》：": [
    "About #{id} \"{title}\": ",
    "Tentang #{id} \"{title}\": "
  ],
  "现在要处理": [
    "Needs you now",
    "Perlu Anda sekarang"
  ],
  "在等别人": [
    "Waiting on others",
    "Menunggu orang lain"
  ],
  "现在没有要你马上处理的事": [
    "Nothing needs you right now",
    "Tidak ada yang perlu segera Anda tangani"
  ],
  "Relay 在盯着": [
    "Relay is watching",
    "Relay sedang memantau"
  ],
  "详情": [
    "Details",
    "Detail"
  ],
  "返回列表": [
    "Back to list",
    "Kembali ke daftar"
  ],
  "问 Relay": [
    "Ask Relay",
    "Tanya Relay"
  ],
  "选一件事，看发生了什么、依据和准备好的下一步。": [
    "Pick an item to see what happened, the evidence, and the next step Relay prepared.",
    "Pilih satu hal untuk melihat apa yang terjadi, buktinya, dan langkah berikutnya yang sudah disiapkan."
  ],
  "未回复邀请": [
    "Not responded",
    "Belum dibalas"
  ],
  "议程": [
    "Agenda",
    "Agenda"
  ],
  "文档": [
    "Doc",
    "Dokumen"
  ],
  "纪要": [
    "Minutes",
    "Notulen"
  ],
  "行动项": [
    "Action items",
    "Tindak lanjut"
  ],
  "组织者：{name}": [
    "Organizer: {name}",
    "Penyelenggara: {name}"
  ],
  "依据（{count} 份材料）": [
    "Evidence ({count} sources)",
    "Bukti ({count} sumber)"
  ],
  "会前 Relay 会只用和这个会确实相关的材料整理准备；也可以现在就整理。": [
    "Before the meeting, Relay prepares notes using only material genuinely related to it. You can also do it now.",
    "Sebelum rapat, Relay menyiapkan catatan hanya dari materi yang benar-benar terkait. Bisa juga sekarang."
  ],
  "纪要里有 {count} 个行动项": [
    "{count} action items in the minutes",
    "{count} tindak lanjut di notulen"
  ],
  "没有找到这次会的纪要，没有提取行动项。": [
    "No minutes found for this meeting, so no action items were extracted.",
    "Notulen rapat ini tidak ditemukan, jadi tidak ada tindak lanjut yang diambil."
  ],
  "会后会去找这次会的纪要，找到后提取行动项。": [
    "After the meeting Relay looks for the minutes and extracts action items.",
    "Setelah rapat, Relay mencari notulen dan mengambil tindak lanjutnya."
  ],
  "整理中…": [
    "Preparing…",
    "Menyiapkan…"
  ],
  "重新整理": [
    "Prepare again",
    "Siapkan ulang"
  ],
  "现在整理会前准备": [
    "Prepare now",
    "Siapkan sekarang"
  ],
  "接下来": [
    "Upcoming",
    "Mendatang"
  ],
  "接下来 3 天没有会。": [
    "No meetings in the next 3 days.",
    "Tidak ada rapat dalam 3 hari ke depan."
  ],
  "刚开过的": [
    "Just ended",
    "Baru selesai"
  ],
  "最近 7 天还没有结果。": [
    "No results in the last 7 days.",
    "Belum ada hasil dalam 7 hari terakhir."
  ],
  "汇总和简报": [
    "Digests and briefs",
    "Ringkasan dan briefing"
  ],
  "汇总": [
    "Digest",
    "Ringkasan"
  ],
  "Relay 发了一份简报": [
    "Relay sent a brief",
    "Relay mengirim briefing"
  ],
  "Relay 发了一份汇总": [
    "Relay sent a digest",
    "Relay mengirim ringkasan"
  ],
  "Relay 提醒了你 {count} 件事": [
    "Relay reminded you of {count} items",
    "Relay mengingatkan {count} hal"
  ],
  "去待处理": [
    "Open To do",
    "Buka Perlu ditangani"
  ],
  "看进展": [
    "See progress",
    "Lihat perkembangan"
  ],
  "提醒准不准": [
    "Are reminders accurate?",
    "Seberapa tepat pengingat?"
  ],
  "来自真实卡片上的反馈：提醒后处理算准，提醒前已处理 / 不归我 / 不值得 / 重复算不准；没反应的单独统计。": [
    "From feedback on real cards: handled after the reminder counts as accurate; already handled, not mine, not worth it or duplicate count as inaccurate. No response is counted separately.",
    "Dari umpan balik pada kartu nyata: ditangani setelah pengingat dihitung tepat; sudah ditangani, bukan urusan saya, tidak perlu, atau duplikat dihitung tidak tepat. Tanpa respons dihitung terpisah."
  ],
  "提醒准确率": [
    "Reminder accuracy",
    "Ketepatan pengingat"
  ],
  "{count} 件有反馈": [
    "{count} with feedback",
    "{count} dengan umpan balik"
  ],
  "迟到率": [
    "Late rate",
    "Tingkat terlambat"
  ],
  "推送的事": [
    "Items pushed",
    "Hal yang dikirim"
  ],
  "{count} 件没反应": [
    "{count} no response",
    "{count} tanpa respons"
  ],
  "先放后台的候选": [
    "Held as candidates",
    "Ditahan sebagai kandidat"
  ],
  "拿不准、没有打扰用户": [
    "Unclear, user not disturbed",
    "Belum jelas, tidak mengganggu pengguna"
  ],
  "按来源": [
    "By source",
    "Per sumber"
  ],
  "来源": [
    "Source",
    "Sumber"
  ],
  "有反馈": [
    "With feedback",
    "Dengan umpan balik"
  ],
  "按人": [
    "By person",
    "Per orang"
  ],
  "没反应": [
    "No response",
    "Tanpa respons"
  ],
  "新建（私聊）": [
    "Created (private chat)",
    "Dibuat (obrolan pribadi)"
  ],
  "私聊": [
    "Private chat",
    "Obrolan pribadi"
  ],
  "群聊": [
    "Group chat",
    "Obrolan grup"
  ],
  "会议纪要": [
    "Meeting minutes",
    "Notulen rapat"
  ],
  "在对话里问": [
    "Ask in chat",
    "Tanya di obrolan"
  ],
  "看这几件": [
    "See these",
    "Lihat ini"
  ],
  "跟进": [
    "Tracking",
    "Pantauan"
  ],
  "最近进展": [
    "Recent progress",
    "Perkembangan terbaru"
  ],
  "Relay 在跟进": [
    "Relay is tracking",
    "Relay sedang memantau"
  ],
  "今天的工作": [
    "Today's work",
    "Pekerjaan hari ini"
  ],
  "今天": [
    "Today",
    "Hari ini"
  ],
  "收起详情栏": [
    "Hide details",
    "Sembunyikan detail"
  ],
  "打开详情栏": [
    "Show details",
    "Tampilkan detail"
  ],
  "需要你 {me} · 在等对方 {others}": [
    "{me} need you · waiting on {others}",
    "{me} perlu Anda · menunggu {others}"
  ],
  "下一场 {time}": [
    "Next {time}",
    "Berikutnya {time}"
  ],
  "近期没有会": [
    "No upcoming meetings",
    "Tidak ada rapat"
  ],
  "安静汇总，不打扰": [
    "Quiet summary, no interruptions",
    "Ringkasan tenang, tanpa gangguan"
  ],
  "同步失败，显示的是上次的结果": [
    "Sync failed — showing the last results",
    "Sinkronisasi gagal — menampilkan hasil terakhir"
  ],
  "已同步 · {time}": [
    "Synced · {time}",
    "Tersinkron · {time}"
  ],
  "正在同步…": [
    "Syncing…",
    "Menyinkronkan…"
  ],
  "只在需要你时提醒": [
    "Only notifies when needed",
    "Hanya memberi tahu saat perlu"
  ],
  "待回复邀请": [
    "Awaiting reply",
    "Menunggu balasan"
  ],
  "简报已就绪": [
    "Brief ready",
    "Briefing siap"
  ],
  "有纪要": [
    "Has minutes",
    "Ada notulen"
  ],
  "时间重叠": [
    "Overlaps",
    "Bentrok"
  ],
  "{count} 人参会": [
    "{count} attendees",
    "{count} peserta"
  ],
  "和《{title}》时间重叠。": [
    "Overlaps with \"{title}\".",
    "Bentrok dengan \"{title}\"."
  ],
  "查看另一场": [
    "See the other",
    "Lihat yang lain"
  ],
  "会前简报": [
    "Prep",
    "Persiapan"
  ],
  "会后行动": [
    "Follow-ups",
    "Tindak lanjut"
  ],
  "整理于 {time}，只用会前已有、和这个会确实相关的材料": [
    "Prepared {time} from material that existed before the meeting and is genuinely related",
    "Disiapkan {time} dari materi yang sudah ada sebelum rapat dan benar-benar terkait"
  ],
  "这个会已经开过了，没有整理会前简报。": [
    "This meeting has ended; no prep was made.",
    "Rapat ini sudah selesai; tidak ada persiapan."
  ],
  "会前会只用和这个会确实相关的材料整理简报；也可以现在就整理。": [
    "Before the meeting Relay prepares a brief from genuinely related material only. You can also do it now.",
    "Sebelum rapat Relay menyiapkan briefing hanya dari materi yang benar-benar terkait. Bisa juga sekarang."
  ],
  "没有找到和这个会直接相关的材料。": [
    "No material directly related to this meeting was found.",
    "Tidak ditemukan materi yang terkait langsung."
  ],
  "会议结束后，Relay 会去找这次会的纪要，找到后提取分给你的行动项。": [
    "After the meeting Relay looks for the minutes and extracts the actions assigned to you.",
    "Setelah rapat Relay mencari notulen dan mengambil tindak lanjut untuk Anda."
  ],
  "正在找这次会的纪要。": [
    "Looking for the minutes.",
    "Sedang mencari notulen."
  ],
  "带着这场会议问 Relay": [
    "Ask Relay about this meeting",
    "Tanya Relay tentang rapat ini"
  ],
  "回复邀请": [
    "Reply to invite",
    "Balas undangan"
  ],
  "现在整理": [
    "Prepare now",
    "Siapkan sekarang"
  ],
  "{count} 张申请，每张单独处理": [
    "{count} requests, each handled separately",
    "{count} permintaan, masing-masing ditangani terpisah"
  ],
  "需要你": [
    "Needs you",
    "Perlu Anda"
  ],
  "现在没有需要你处理的事。": [
    "Nothing needs you right now.",
    "Tidak ada yang perlu Anda tangani."
  ],
  "{time} 有会议时间重叠，确认一下参会安排。": [
    "Meetings overlap at {time} — check which to attend.",
    "Rapat bentrok pukul {time} — pastikan mana yang dihadiri."
  ],
  "{count} 场": [
    "{count}",
    "{count}"
  ],
  "只用和你及这个会相关、你有权看的材料": [
    "Only material related to you and the meeting that you can access",
    "Hanya materi terkait yang bisa Anda akses"
  ],
  "这件事已经结束了。": [
    "This item has ended.",
    "Hal ini sudah selesai."
  ],
  "带着这件事问 Relay": [
    "Ask Relay about this",
    "Tanya Relay tentang ini"
  ],
  "找不到这个会了（可能已取消）。": [
    "Meeting not found (it may have been cancelled).",
    "Rapat tidak ditemukan (mungkin dibatalkan)."
  ],
  "为什么相关": [
    "Why related",
    "Mengapa terkait"
  ],
  "用于会议《{title}》的会前简报": [
    "Used for the prep of \"{title}\"",
    "Dipakai untuk persiapan \"{title}\""
  ],
  "在飞书打开原文": [
    "Open in Feishu",
    "Buka di Feishu"
  ],
  "这份材料在会议描述或 Relay 的记录里，没有单独的原文链接。": [
    "This material comes from the meeting description or Relay's records; there's no separate link.",
    "Materi ini dari deskripsi rapat atau catatan Relay; tidak ada tautan terpisah."
  ],
  "详情栏": [
    "Details",
    "Detail"
  ],
  "关于会议《{title}》（{when}）：": [
    "About the meeting \"{title}\" ({when}): ",
    "Tentang rapat \"{title}\" ({when}): "
  ],
  "移除": [
    "Remove",
    "Hapus"
  ],
  "我先处理什么？": [
    "What should I do first?",
    "Apa yang harus saya kerjakan dulu?"
  ],
  "准备下一场会议": [
    "Prepare for my next meeting",
    "Siapkan rapat berikutnya"
  ],
  "问 Relay，或交给它一件事…": [
    "Ask Relay, or hand it something…",
    "Tanya Relay, atau serahkan sesuatu…"
  ],
  "对外发送与审批，都会先让你确认。": [
    "Anything sent out or approved asks you first.",
    "Apa pun yang dikirim atau disetujui akan meminta konfirmasi Anda dulu."
  ],
  "什么时候处理的？": [
    "When was it handled?",
    "Kapan ditangani?"
  ],
  "提醒后处理完了": [
    "After the reminder",
    "Setelah pengingat"
  ],
  "暂时不跟进": [
    "Pause for now",
    "Tunda dulu"
  ],
  "已核对": [
    "Verified",
    "Terverifikasi"
  ],
  "核对不一致": [
    "Mismatch",
    "Tidak cocok"
  ],
  "未核对": [
    "Not verified",
    "Belum diverifikasi"
  ],
  "下载": [
    "Download",
    "Unduh"
  ],
  "要回 {reply} · 要看 {review}": [
    "{reply} to reply · {review} to read",
    "{reply} dibalas · {review} dibaca"
  ],
  "没有要处理的邮件": [
    "No mail to handle",
    "Tidak ada email"
  ],
  "要你回复": [
    "Needs your reply",
    "Perlu balasan Anda"
  ],
  "要你看": [
    "Needs your review",
    "Perlu Anda baca"
  ],
  "在等对方回信": [
    "Waiting for a reply",
    "Menunggu balasan"
  ],
  "没有要你处理的邮件。知会、群发和系统通知不会出现在这里。": [
    "No mail needs you. FYI, mass mail and system notices don't show here.",
    "Tidak ada email yang perlu Anda tangani. Info, email massal, dan notifikasi sistem tidak muncul di sini."
  ],
  "回复全部": [
    "Reply all",
    "Balas semua"
  ],
  "只回复发件人": [
    "Reply to sender only",
    "Hanya balas pengirim"
  ],
  "线程里之前 {count} 封往来": [
    "{count} earlier in thread",
    "{count} sebelumnya di utas"
  ],
  "附件 {names}": [
    "Attachments {names}",
    "Lampiran {names}"
  ],
  "正文里 {count} 个飞书文档": [
    "{count} Feishu docs linked",
    "{count} dokumen Feishu ditautkan"
  ],
  "相关会议《{title}》": [
    "Related meeting \"{title}\"",
    "Rapat terkait \"{title}\""
  ],
  "转发": [
    "Forward",
    "Teruskan"
  ],
  "转发给（邮箱，多个用逗号分开）": [
    "Forward to (emails, comma-separated)",
    "Teruskan ke (email, pisahkan dengan koma)"
  ],
  "附言": [
    "Note",
    "Catatan"
  ],
  "带上原附件": [
    "Include attachments",
    "Sertakan lampiran"
  ],
  "准备中…": [
    "Preparing…",
    "Menyiapkan…"
  ],
  "准备转发": [
    "Prepare forward",
    "Siapkan penerusan"
  ],
  "处理中": [
    "Working",
    "Diproses"
  ],
  "没做成": [
    "Failed",
    "Gagal"
  ],
  "在飞书云空间打开": [
    "Open in Feishu Drive",
    "Buka di Feishu Drive"
  ],
  "存进飞书云空间": [
    "Save to Feishu Drive",
    "Simpan ke Feishu Drive"
  ],
  "在后台做，做完会在飞书里告诉你；可以先去做别的。": [
    "Running in the background — you'll get a Feishu message when it's done.",
    "Berjalan di latar — Anda akan diberi tahu di Feishu."
  ],
  "云空间": [
    "Drive",
    "Drive"
  ],
  "排队中": [
    "Queued",
    "Antre"
  ],
  "生成文件": [
    "Generating",
    "Membuat file"
  ],
  "存进飞书云空间中": [
    "Saving to Drive",
    "Menyimpan ke Drive"
  ],
  "稍后重试": [
    "Retrying soon",
    "Coba lagi nanti"
  ],
  "数据来源": [
    "Data sources",
    "Sumber data"
  ],
  "没有注明数据来源：数据和结论还没有核实": [
    "No data sources noted: the data and conclusions haven't been verified",
    "Sumber data tidak dicatat: data dan kesimpulan belum diverifikasi"
  ],
  "进展依据（{count} 条）": [
    "Evidence ({count})",
    "Bukti ({count})"
  ],
  "相关事项": [
    "Related items",
    "Hal terkait"
  ],
  "没有权限，没用到": [
    "No access — not used",
    "Tanpa akses — tidak dipakai"
  ],
  "读取失败，没用到": [
    "Couldn't read — not used",
    "Gagal dibaca — tidak dipakai"
  ],
  "这个飞书账号不属于这个工作区，无法登录。": [
    "This Feishu account doesn't belong to this workspace.",
    "Akun Feishu ini bukan bagian dari workspace ini."
  ],
  "这个工作区还没有接入飞书，请用邮箱登录。": [
    "This workspace isn't connected to Feishu yet — sign in with email.",
    "Workspace ini belum terhubung ke Feishu — masuk dengan email."
  ],
  "你在这个工作区的账号已停用，请联系管理员。": [
    "Your account in this workspace is deactivated. Contact an admin.",
    "Akun Anda di workspace ini dinonaktifkan. Hubungi admin."
  ],
  "选择要进入的工作区": [
    "Choose a workspace",
    "Pilih workspace"
  ],
  "你的名字": [
    "Your name",
    "Nama Anda"
  ],
  "工作区名称（公司或团队）": [
    "Workspace name (company or team)",
    "Nama workspace (perusahaan atau tim)"
  ],
  "邮箱": [
    "Email",
    "Email"
  ],
  "密码": [
    "Password",
    "Kata sandi"
  ],
  "请稍候…": [
    "Please wait…",
    "Mohon tunggu…"
  ],
  "创建工作区": [
    "Create workspace",
    "Buat workspace"
  ],
  "登录": [
    "Sign in",
    "Masuk"
  ],
  "新建一个工作区": [
    "Create a new workspace",
    "Buat workspace baru"
  ],
  "已有账号，去登录": [
    "Have an account? Sign in",
    "Sudah punya akun? Masuk"
  ],
  "或": [
    "or",
    "atau"
  ],
  "你被邀请加入工作区「{name}」": [
    "You've been invited to join \"{name}\"",
    "Anda diundang bergabung ke \"{name}\""
  ],
  "你的登录密码": [
    "Your password",
    "Kata sandi Anda"
  ],
  "设置登录密码（至少 8 位）": [
    "Set a password (at least 8 characters)",
    "Buat kata sandi (minimal 8 karakter)"
  ],
  "加入工作区": [
    "Join workspace",
    "Gabung workspace"
  ],
  "邀请链接无效": [
    "Invalid invitation link",
    "Tautan undangan tidak valid"
  ],
  "所有者": [
    "Owner",
    "Pemilik"
  ],
  "管理员": [
    "Admin",
    "Admin"
  ],
  "成员": [
    "Member",
    "Anggota"
  ],
  "已保存。之后也可以用邮箱和密码登录。": [
    "Saved. You can now also sign in with email and password.",
    "Tersimpan. Anda kini juga bisa masuk dengan email dan kata sandi."
  ],
  "切换工作区": [
    "Switch workspace",
    "Ganti workspace"
  ],
  "修改登录密码": [
    "Change password",
    "Ubah kata sandi"
  ],
  "设置邮箱登录": [
    "Set up email sign-in",
    "Atur masuk dengan email"
  ],
  "登录邮箱": [
    "Sign-in email",
    "Email masuk"
  ],
  "登录邮箱：{email}": [
    "Sign-in email: {email}",
    "Email masuk: {email}"
  ],
  "当前密码": [
    "Current password",
    "Kata sandi saat ini"
  ],
  "新密码（至少 8 位）": [
    "New password (at least 8 characters)",
    "Kata sandi baru (minimal 8 karakter)"
  ],
  "工作区名称": [
    "Workspace name",
    "Nama workspace"
  ],
  "成员（{count}）": [
    "Members ({count})",
    "Anggota ({count})"
  ],
  "你": [
    "You",
    "Anda"
  ],
  "飞书": [
    "Feishu",
    "Feishu"
  ],
  "邮箱登录": [
    "Email sign-in",
    "Masuk dengan email"
  ],
  "角色": [
    "Role",
    "Peran"
  ],
  "停用": [
    "Deactivate",
    "Nonaktifkan"
  ],
  "恢复": [
    "Reactivate",
    "Aktifkan kembali"
  ],
  "邀请成员": [
    "Invite members",
    "Undang anggota"
  ],
  "生成邀请链接": [
    "Create invite link",
    "Buat tautan undangan"
  ],
  "邀请链接": [
    "Invite link",
    "Tautan undangan"
  ],
  "7 天内有效，只能用一次。目前需要你把链接发给对方。": [
    "Valid for 7 days, single use. Send the link to them yourself for now.",
    "Berlaku 7 hari, sekali pakai. Untuk saat ini kirimkan tautannya sendiri."
  ],
  "等待接受": [
    "Pending",
    "Menunggu"
  ],
  "撤回": [
    "Revoke",
    "Cabut"
  ],
  "飞书接入": [
    "Feishu connection",
    "Koneksi Feishu"
  ],
  "飞书是可选的外部渠道：接入后成员可以用飞书登录，Relay 能读取飞书里的邮件、日程、审批和消息，并通过飞书提醒。没接入时，Relay 本身的对话、记忆和任务照常可用。": [
    "Feishu is an optional external channel: once connected, members can sign in with Feishu and Relay can read mail, calendar, approvals and messages there and remind via Feishu. Without it, Relay's chat, memory and tasks still work.",
    "Feishu adalah kanal eksternal opsional: setelah terhubung, anggota bisa masuk dengan Feishu dan Relay bisa membaca email, kalender, persetujuan, dan pesan di sana serta mengingatkan lewat Feishu. Tanpanya, obrolan, memori, dan tugas Relay tetap berjalan."
  ],
  "状态": [
    "Status",
    "Status"
  ],
  "已连通": [
    "Connected",
    "Terhubung"
  ],
  "连接失败": [
    "Connection failed",
    "Koneksi gagal"
  ],
  "未验证": [
    "Not verified",
    "Belum diverifikasi"
  ],
  "未接入": [
    "Not connected",
    "Belum terhubung"
  ],
  "企业 Tenant Key（只允许这家企业的飞书账号登录）": [
    "Tenant Key (only this company's Feishu accounts can sign in)",
    "Tenant Key (hanya akun Feishu perusahaan ini yang bisa masuk)"
  ],
  "默认工作区沿用服务器上的飞书配置，这里只读；需要更换时请联系平台运维。": [
    "The default workspace uses the server's Feishu settings, so they're read-only here. Contact the platform team to change them.",
    "Workspace default memakai pengaturan Feishu dari server, jadi hanya bisa dilihat di sini. Hubungi tim platform untuk mengubahnya."
  ],
  "事件订阅和卡片回调的请求地址（订阅“接收消息”事件和“卡片回传交互”）": [
    "Request URL for event subscriptions and card callbacks (subscribe to \"Receive messages\" and \"Card action\")",
    "URL permintaan untuk langganan event dan callback kartu (langganan \"Terima pesan\" dan \"Aksi kartu\")"
  ],
  "成员用飞书登录这个工作区的链接": [
    "Link for members to sign in to this workspace with Feishu",
    "Tautan bagi anggota untuk masuk ke workspace ini dengan Feishu"
  ],
  "这个飞书应用已经接入了另一个工作区。每个工作区需要使用自己的飞书应用。": [
    "This Feishu app is already connected to another workspace. Each workspace needs its own Feishu app.",
    "Aplikasi Feishu ini sudah terhubung ke workspace lain. Setiap workspace perlu aplikasi Feishu sendiri."
  ],
  "未约定": [
    "Not agreed",
    "Belum disepakati"
  ],
  "取消这个请求？对方会收到通知。": [
    "Cancel this request? The other person will be notified.",
    "Batalkan permintaan ini? Pihak lain akan diberi tahu."
  ],
  "你请 {name}": [
    "You asked {name}",
    "Anda meminta {name}"
  ],
  "{name} 请你": [
    "{name} asked you",
    "{name} meminta Anda"
  ],
  "要做什么": [
    "What's needed",
    "Yang perlu dikerjakan"
  ],
  "交付": [
    "Deliverable",
    "Hasil yang diserahkan"
  ],
  "怎样算完成": [
    "Done when",
    "Dianggap selesai jika"
  ],
  "没写": [
    "Not specified",
    "Tidak ditulis"
  ],
  "期限": [
    "Deadline",
    "Tenggat"
  ],
  "共享的材料": [
    "Shared materials",
    "Materi yang dibagikan"
  ],
  "{name} 提出修改": [
    "{name} proposed changes",
    "{name} mengusulkan perubahan"
  ],
  "{name} 提交的结果": [
    "Submitted by {name}",
    "Hasil yang diserahkan {name}"
  ],
  "期限（可不填）": [
    "Deadline (optional)",
    "Tenggat (opsional)"
  ],
  "材料（每行一份：标题 + https 链接，或直接贴内容）": [
    "Materials (one per line: title + https link, or paste the content)",
    "Materi (satu per baris: judul + tautan https, atau tempel isinya)"
  ],
  "确定": [
    "Confirm",
    "Konfirmasi"
  ],
  "这份协作已经结束。": [
    "This collaboration has ended.",
    "Kolaborasi ini sudah selesai."
  ],
  "等 {name} 处理。": [
    "Waiting for {name}.",
    "Menunggu {name}."
  ],
  "变更记录（{count}）": [
    "History ({count})",
    "Riwayat ({count})"
  ],
  "对方只能看到这里写明的内容和共享的材料，看不到你的对话和记忆。": [
    "The other person only sees what's written here and the shared materials — not your conversations or memory.",
    "Pihak lain hanya melihat isi yang ditulis di sini dan materi yang dibagikan — bukan percakapan atau memori Anda."
  ],
  "这个工作区里还没有别的成员。可以请管理员在“工作区设置”里邀请同事。": [
    "There are no other members in this workspace yet. Ask an admin to invite colleagues in Workspace settings.",
    "Belum ada anggota lain di workspace ini. Minta admin mengundang rekan di Pengaturan workspace."
  ],
  "请谁": [
    "Ask whom",
    "Minta kepada siapa"
  ],
  "选择同事": [
    "Choose a colleague",
    "Pilih rekan"
  ],
  "标题": [
    "Title",
    "Judul"
  ],
  "要做什么（背景、为什么）": [
    "What's needed (background, why)",
    "Yang perlu dikerjakan (latar belakang, alasan)"
  ],
  "交付什么": [
    "What to deliver",
    "Apa yang diserahkan"
  ],
  "怎样算完成（可不填）": [
    "Done when (optional)",
    "Dianggap selesai jika (opsional)"
  ],
  "期限（可不填，没约定就不填）": [
    "Deadline (optional — leave blank if none was agreed)",
    "Tenggat (opsional — kosongkan jika belum disepakati)"
  ],
  "共享给对方的材料（每行一份：标题 + https 链接，或直接贴内容）": [
    "Materials to share (one per line: title + https link, or paste the content)",
    "Materi untuk dibagikan (satu per baris: judul + tautan https, atau tempel isinya)"
  ],
  "对方会在“待处理”里收到，由本人决定接受、拒绝或提出修改。只有这里写的内容会给对方看。": [
    "They'll get it in their To-do list and decide themselves whether to accept, decline or propose changes. Only what you write here is shared.",
    "Mereka akan menerimanya di daftar Perlu ditangani dan memutuskan sendiri untuk menerima, menolak, atau mengusulkan perubahan. Hanya isi di sini yang dibagikan."
  ],
  "发出请求": [
    "Send request",
    "Kirim permintaan"
  ],
  "请同一个工作区的同事做事，对方接受后完成并提交，你来验收。也可以在对话里说“请 Budi 周五前把报价单整理好”。": [
    "Ask a colleague in this workspace to do something. They accept, do it and submit; you review. You can also say in chat: \"Ask Budi to prepare the quotation by Friday.\"",
    "Minta rekan di workspace ini mengerjakan sesuatu. Mereka menerima, mengerjakan, lalu menyerahkan; Anda memeriksa. Bisa juga lewat obrolan: \"Minta Budi menyiapkan penawaran sebelum Jumat.\""
  ],
  "请同事帮忙": [
    "Ask a colleague",
    "Minta bantuan rekan"
  ],
  "轮到你（{count}）": [
    "Your turn ({count})",
    "Giliran Anda ({count})"
  ],
  "没有要你处理的协作。": [
    "Nothing needs you right now.",
    "Tidak ada yang perlu Anda tangani."
  ],
  "在等对方（{count}）": [
    "Waiting on others ({count})",
    "Menunggu pihak lain ({count})"
  ],
  "没有在等对方的协作。": [
    "Not waiting on anyone.",
    "Tidak sedang menunggu siapa pun."
  ],
  "看已结束的": [
    "Show ended",
    "Lihat yang sudah selesai"
  ],
  "提出修改": [
    "Propose changes",
    "Usulkan perubahan"
  ],
  "提交结果": [
    "Submit result",
    "Serahkan hasil"
  ],
  "同意修改": [
    "Agree to changes",
    "Setujui perubahan"
  ],
  "修改要求": [
    "Change the request",
    "Ubah permintaan"
  ],
  "验收通过": [
    "Approve",
    "Terima hasil"
  ],
  "退回修改": [
    "Send back",
    "Kembalikan untuk diperbaiki"
  ],
  "取消请求": [
    "Cancel request",
    "Batalkan permintaan"
  ],
  "拒绝的理由": [
    "Reason for declining",
    "Alasan menolak"
  ],
  "为什么要改、想怎么改": [
    "Why and how you'd change it",
    "Mengapa dan bagaimana ingin diubah"
  ],
  "交付了什么": [
    "What you're delivering",
    "Apa yang Anda serahkan"
  ],
  "哪里需要改": [
    "What needs to change",
    "Apa yang perlu diubah"
  ],
  "打开协作": [
    "Open collaboration",
    "Buka kolaborasi"
  ],
  "和同事协作": [
    "Work with colleagues",
    "Kolaborasi dengan rekan"
  ],
  "和同事的协作": [
    "Collaboration",
    "Kolaborasi"
  ],
  "等对方回应": [
    "Waiting for response",
    "Menunggu tanggapan"
  ],
  "对方提出了修改": [
    "Changes proposed",
    "Ada usulan perubahan"
  ],
  "进行中": [
    "In progress",
    "Sedang dikerjakan"
  ],
  "已提交，等验收": [
    "Submitted, awaiting review",
    "Sudah diserahkan, menunggu diperiksa"
  ],
  "已退回修改": [
    "Sent back for changes",
    "Dikembalikan untuk diperbaiki"
  ],
  "等对方接受": [
    "Waiting for them to accept",
    "Menunggu diterima"
  ],
  "等你回应": [
    "Waiting for your response",
    "Menunggu tanggapan Anda"
  ],
  "等对方回应你的修改": [
    "Waiting for them to respond to your changes",
    "Menunggu tanggapan atas usulan Anda"
  ],
  "已提交，等你验收": [
    "Submitted — your review",
    "Sudah diserahkan — perlu Anda periksa"
  ],
  "已提交，等对方验收": [
    "Submitted — awaiting their review",
    "Sudah diserahkan — menunggu diperiksa"
  ],
  "已退回，等对方修改": [
    "Sent back — waiting for changes",
    "Dikembalikan — menunggu perbaikan"
  ],
  "被退回，需要修改": [
    "Sent back — needs changes",
    "Dikembalikan — perlu diperbaiki"
  ],
  "邮箱地址": [
    "Email address",
    "Alamat email"
  ],
  "密码（Gmail、Outlook 等要用“应用专用密码”）": [
    "Password (Gmail, Outlook and others need an app password)",
    "Kata sandi (Gmail, Outlook, dll. perlu sandi aplikasi)"
  ],
  "服务器设置": [
    "Server settings",
    "Pengaturan server"
  ],
  "收信服务器（IMAP）": [
    "Incoming server (IMAP)",
    "Server masuk (IMAP)"
  ],
  "端口": [
    "Port",
    "Port"
  ],
  "发信服务器（SMTP）": [
    "Outgoing server (SMTP)",
    "Server keluar (SMTP)"
  ],
  "登录名（通常就是邮箱地址）": [
    "Username (usually your email address)",
    "Nama pengguna (biasanya alamat email)"
  ],
  "“已发送”文件夹（找不到时才需要填）": [
    "Sent folder (only if it isn't found automatically)",
    "Folder Terkirim (isi hanya jika tidak ditemukan otomatis)"
  ],
  "正在连接…": [
    "Connecting…",
    "Menghubungkan…"
  ],
  "保存并测试": [
    "Save and test",
    "Simpan dan uji"
  ],
  "接入": [
    "Connect",
    "Hubungkan"
  ],
  "断开这个邮箱？已经读进来的邮件和事项会保留。": [
    "Disconnect this mailbox? Mail and items already read in are kept.",
    "Putuskan kotak surat ini? Email dan item yang sudah dibaca tetap disimpan."
  ],
  "断开": [
    "Disconnect",
    "Putuskan"
  ],
  "日历订阅链接（ICS）": [
    "Calendar subscription link (ICS)",
    "Tautan langganan kalender (ICS)"
  ],
  "Google 日历：设置 → 你的日历 → “iCal 格式的私密地址”；Outlook：设置 → 日历 → 共享日历 → 发布日历 → ICS 链接。只读：Relay 用它做会前准备和简报，不会改你的日历。": [
    "Google Calendar: Settings → your calendar → \"Secret address in iCal format\". Outlook: Settings → Calendar → Shared calendars → Publish a calendar → ICS link. Read-only: Relay uses it for meeting prep and briefs and never changes your calendar.",
    "Google Kalender: Setelan → kalender Anda → \"Alamat rahasia dalam format iCal\". Outlook: Pengaturan → Kalender → Kalender bersama → Terbitkan kalender → tautan ICS. Hanya-baca: Relay memakainya untuk persiapan rapat dan ringkasan, tidak mengubah kalender Anda."
  ],
  "断开这个日历？": [
    "Disconnect this calendar?",
    "Putuskan kalender ini?"
  ],
  "邮箱和日历": [
    "Mail and calendar",
    "Email dan kalender"
  ],
  "你在用飞书的邮箱和日历。如果你的工作邮箱不是飞书邮箱，可以在这里接入，Relay 就读这个邮箱。": [
    "You're using Feishu mail and calendar. If your work mailbox isn't Feishu Mail, connect it here and Relay will read that one.",
    "Anda memakai email dan kalender Feishu. Jika email kerja Anda bukan Feishu Mail, hubungkan di sini dan Relay akan membacanya."
  ],
  "接入你自己的工作邮箱和日历，Relay 就能替你读信、跟进要你处理的事、代拟回复、做会前准备和简报。": [
    "Connect your work mailbox and calendar so Relay can read your mail, track what needs you, draft replies, and prepare meetings and briefs.",
    "Hubungkan email dan kalender kerja Anda agar Relay bisa membaca email, mengikuti hal yang perlu Anda tangani, menyiapkan balasan, persiapan rapat, dan ringkasan."
  ],
  "最近验证 {time}": [
    "Last checked {time}",
    "Terakhir diperiksa {time}"
  ],
  "浏览器通知": [
    "Browser notifications",
    "Notifikasi browser"
  ],
  "这个浏览器不支持通知": [
    "This browser doesn't support notifications",
    "Browser ini tidak mendukung notifikasi"
  ],
  "Relay 有需要你马上知道的事时，在浏览器里弹出通知（打开着 Relay 的标签页时）。": [
    "Show a browser notification when Relay has something you need to know now (while a Relay tab is open).",
    "Tampilkan notifikasi browser saat Relay punya hal yang perlu segera Anda ketahui (selama tab Relay terbuka)."
  ],
  "今天的简报好了": [
    "Today's brief is ready",
    "Ringkasan hari ini sudah siap"
  ],
  "有事需要你看一下": [
    "Something needs your attention",
    "Ada yang perlu Anda lihat"
  ],
  "这台 Mac": [
    "This Mac",
    "Mac ini"
  ],
  "已断开": [
    "Disconnected",
    "Terputus"
  ],
  "这台 Mac 在网页上被撤销了，助理现在用不了它的文件夹。": [
    "This Mac was revoked on the web, so the assistant can't use its folders right now.",
    "Mac ini dicabut di web, jadi asisten tidak bisa memakai foldernya saat ini."
  ],
  "重新连接": [
    "Reconnect",
    "Hubungkan lagi"
  ],
  "已连接到你的账号。": [
    "Connected to your account.",
    "Terhubung ke akun Anda."
  ],
  "正在连接到你的账号…": [
    "Connecting to your account…",
    "Menghubungkan ke akun Anda…"
  ],
  "助理只能使用下面授权的文件夹：读取用来看资料，写入只会新建文件、不会覆盖。完整路径只留在这台 Mac 上。": [
    "The assistant can only use the folders authorised below: reading to look at material, writing only ever creates new files and never overwrites. Full paths stay on this Mac.",
    "Asisten hanya bisa memakai folder yang diizinkan di bawah: baca untuk melihat materi, tulis hanya membuat file baru dan tidak pernah menimpa. Path lengkap tetap di Mac ini."
  ],
  "还没有授权文件夹。": [
    "No folders authorised yet.",
    "Belum ada folder yang diizinkan."
  ],
  "在访达中显示": [
    "Show in Finder",
    "Tampilkan di Finder"
  ],
  "取消授权「{name}」？": [
    "Stop authorising \"{name}\"?",
    "Cabut izin \"{name}\"?"
  ],
  "取消授权": [
    "Remove",
    "Cabut izin"
  ],
  "允许读取": [
    "Allow reading",
    "Izinkan baca"
  ],
  "允许写入新文件": [
    "Allow writing new files",
    "Izinkan menulis file baru"
  ],
  "授权一个文件夹": [
    "Authorise a folder",
    "Izinkan sebuah folder"
  ],
  "登录过的电脑": [
    "Signed-in computers",
    "Komputer yang pernah masuk"
  ],
  "在线": [
    "Online",
    "Online"
  ],
  "上次在线 {time}": [
    "Last online {time}",
    "Terakhir online {time}"
  ],
  "不在线": [
    "Offline",
    "Offline"
  ],
  "授权了 {count} 个文件夹": [
    "{count} folders authorised",
    "{count} folder diizinkan"
  ],
  "撤销「{name}」？它会立刻断开，助理不能再用它的文件夹。": [
    "Revoke \"{name}\"? It disconnects immediately and the assistant can no longer use its folders.",
    "Cabut \"{name}\"? Langsung terputus dan asisten tidak bisa lagi memakai foldernya."
  ],
  "已保存。助理会用这些信息理解你的工作。": [
    "Saved. Your assistant uses this to understand your work.",
    "Tersimpan. Asisten memakai ini untuk memahami pekerjaan Anda."
  ],
  "我的资料": [
    "My profile",
    "Profil saya"
  ],
  "部门：{dept} · 直属上级：{manager}": [
    "Department: {dept} · Manager: {manager}",
    "Departemen: {dept} · Atasan: {manager}"
  ],
  "岗位": [
    "Job title",
    "Jabatan"
  ],
  "负责什么（客户、线路、项目……）": [
    "Responsibilities (customers, routes, projects…)",
    "Tanggung jawab (pelanggan, rute, proyek…)"
  ],
  "新建工作区": [
    "New workspace",
    "Workspace baru"
  ],
  "创建": [
    "Create",
    "Buat"
  ],
  "未设置": [
    "Not set",
    "Belum diatur"
  ],
  "部门": [
    "Department",
    "Departemen"
  ],
  "已从飞书同步 {depts} 个部门、{members} 位成员；手工改过的没有覆盖。": [
    "Synced {depts} departments and {members} members from Feishu; manual edits were kept.",
    "Tersinkron {depts} departemen dan {members} anggota dari Feishu; perubahan manual tetap dipertahankan."
  ],
  "从飞书通讯录同步": [
    "Sync from Feishu directory",
    "Sinkronkan dari direktori Feishu"
  ],
  "同步部门、上级和岗位；你在这里手工改过的不会被覆盖。": [
    "Syncs departments, managers and job titles; anything you edited here is never overwritten.",
    "Menyinkronkan departemen, atasan, dan jabatan; yang Anda ubah di sini tidak akan ditimpa."
  ],
  "还没有部门。": [
    "No departments yet.",
    "Belum ada departemen."
  ],
  "负责人：{name}": [
    "Lead: {name}",
    "Pimpinan: {name}"
  ],
  "来自飞书": [
    "From Feishu",
    "Dari Feishu"
  ],
  "部门负责人": [
    "Department lead",
    "Pimpinan departemen"
  ],
  "新的部门名称": [
    "New department name",
    "Nama departemen baru"
  ],
  "改名": [
    "Rename",
    "Ganti nama"
  ],
  "删除部门「{name}」？下级部门会挂到它的上级，成员不会被删除。": [
    "Delete department \"{name}\"? Sub-departments move up to its parent; no members are removed.",
    "Hapus departemen \"{name}\"? Sub-departemen dipindah ke induknya; anggota tidak dihapus."
  ],
  "部门名称": [
    "Department name",
    "Nama departemen"
  ],
  "上级部门": [
    "Parent department",
    "Departemen induk"
  ],
  "顶级部门": [
    "Top level",
    "Tingkat teratas"
  ],
  "添加部门": [
    "Add department",
    "Tambah departemen"
  ],
  "成员的部门与上级": [
    "Members' departments and managers",
    "Departemen dan atasan anggota"
  ],
  "上级用来判断谁的事更重要（上级找他的事会优先告诉他）；不用于派任务。": [
    "Managers decide what matters more (requests from a manager are surfaced first); not for assigning tasks.",
    "Atasan dipakai untuk menentukan prioritas (permintaan atasan didahulukan); bukan untuk membagi tugas."
  ],
  "未填岗位": [
    "No job title",
    "Belum ada jabatan"
  ],
  "未设置部门": [
    "No department",
    "Belum ada departemen"
  ],
  "直属上级": [
    "Manager",
    "Atasan langsung"
  ],
  "团队": [
    "Teams",
    "Tim"
  ],
  "可以跨部门的一组人（例如项目组）。负责人能看成员的事项数量，看不到内容。": [
    "A group of people across departments (e.g. a project group). Leads see how many items members have, never the content.",
    "Sekelompok orang lintas departemen (mis. tim proyek). Pimpinan melihat jumlah item anggota, bukan isinya."
  ],
  "还没有团队。": [
    "No teams yet.",
    "Belum ada tim."
  ],
  "完成": [
    "Done",
    "Selesai"
  ],
  "看汇总": [
    "Summary",
    "Ringkasan"
  ],
  "删除团队「{name}」？": [
    "Delete team \"{name}\"?",
    "Hapus tim \"{name}\"?"
  ],
  "负责人": [
    "Lead",
    "Pimpinan"
  ],
  "团队负责人": [
    "Team lead",
    "Pimpinan tim"
  ],
  "还没有成员": [
    "No members yet",
    "Belum ada anggota"
  ],
  "团队名称": [
    "Team name",
    "Nama tim"
  ],
  "建立团队": [
    "Create team",
    "Buat tim"
  ],
  "要处理": [
    "To do",
    "Perlu ditangani"
  ],
  "逾期": [
    "Overdue",
    "Terlambat"
  ],
  "我负责的团队": [
    "Teams I lead",
    "Tim yang saya pimpin"
  ],
  "{field}：未设置": [
    "{field}: not set",
    "{field}: belum diatur"
  ],
  "按提示词版本对比对话": [
    "Conversations by prompt version",
    "Percakapan per versi prompt"
  ],
  "改了系统提示词后，看没回答、勉强作答、工具出错有没有变多（统计期内）。": [
    "After a system prompt change, check whether unanswered turns, forced answers or tool errors went up (within this period).",
    "Setelah prompt sistem diubah, periksa apakah jawaban kosong, jawaban terpaksa, atau error alat meningkat (dalam periode ini)."
  ],
  "版本": [
    "Version",
    "Versi"
  ],
  "对话轮数": [
    "Turns",
    "Giliran"
  ],
  "没回答": [
    "No answer",
    "Tak terjawab"
  ],
  "勉强作答": [
    "Forced answer",
    "Jawaban terpaksa"
  ],
  "工具出错": [
    "Tool errors",
    "Error alat"
  ],
  "每轮工具中位数": [
    "Median tools per turn",
    "Median alat per giliran"
  ],
  "后台判断的准确率": [
    "Background judgement accuracy",
    "Akurasi penilaian di latar belakang"
  ],
  "每次后台判断都会记下；对错来自真实反馈（卡片上的“处理了 / 不归我”、草稿发出还是取消、复盘、规则启用与否），拿不准的不计。": [
    "Every background judgement is recorded; right or wrong comes from real feedback (\"handled / not mine\" on cards, drafts sent or cancelled, reviews, rules switched on or not). Uncertain cases are not counted.",
    "Setiap penilaian di latar belakang dicatat; benar atau salah berasal dari umpan balik nyata (\"sudah ditangani / bukan tugas saya\" di kartu, draf dikirim atau dibatalkan, tinjauan, aturan diaktifkan atau tidak). Kasus yang tidak pasti tidak dihitung."
  ],
  "这段时间还没有记录。": [
    "No records in this period yet.",
    "Belum ada catatan pada periode ini."
  ],
  "判断": [
    "Judgement",
    "Penilaian"
  ],
  "调用": [
    "Calls",
    "Panggilan"
  ],
  "有对错的样本": [
    "Labelled (right / partly / wrong)",
    "Berlabel (benar / sebagian / salah)"
  ],
  "准确率": [
    "Accuracy",
    "Akurasi"
  ],
  "耗时中位数": [
    "Median time",
    "Median waktu"
  ],
  "“有对错的样本”依次是：对 / 部分对 / 错。准确率里部分对算一半。": [
    "Labelled samples are right / partly / wrong; partly counts as half in accuracy.",
    "Sampel berlabel: benar / sebagian / salah; sebagian dihitung setengah dalam akurasi."
  ],
  "邮件分级": [
    "Email triage",
    "Pemilahan email"
  ],
  "长期任务完成核对": [
    "Task completion check",
    "Pemeriksaan penyelesaian tugas"
  ],
  "整理提醒规则": [
    "Reminder rule proposals",
    "Usulan aturan pengingat"
  ],
  "群聊 / 私聊提取": [
    "Chat extraction",
    "Ekstraksi obrolan"
  ],
  "聊天提取（第二遍）": [
    "Chat extraction (second pass)",
    "Ekstraksi obrolan (putaran kedua)"
  ],
  "来信是否回应在等的事": [
    "Reply to a waiting item?",
    "Balasan untuk hal yang ditunggu?"
  ],
  "回复后的状态": [
    "State after reply",
    "Status setelah balasan"
  ],
  "会议行动项": [
    "Meeting action items",
    "Tindak lanjut rapat"
  ],
  "长附件要点": [
    "Long attachment summary",
    "Ringkasan lampiran panjang"
  ],
  "早上简报": [
    "Morning brief",
    "Ringkasan pagi"
  ],
  "团队动态": [
    "Team digest",
    "Kabar tim"
  ],
  "审批摘要": [
    "Approval summary",
    "Ringkasan persetujuan"
  ],
  "跟进邮件草稿": [
    "Follow-up drafts",
    "Draf tindak lanjut"
  ],
  "提醒的说法": [
    "Reminder wording",
    "Kalimat pengingat"
  ],
  "已填写（留空表示不改）": [
    "Set (leave blank to keep)",
    "Sudah diisi (kosongkan untuk tetap)"
  ],
  "飞书后台的重定向 URL 填：{url}": [
    "Set the redirect URL in Feishu to: {url}",
    "Isi URL pengalihan di Feishu dengan: {url}"
  ],
  "测试连接": [
    "Test connection",
    "Uji koneksi"
  ],
  "当前工作区：{name}": [
    "Current workspace: {name}",
    "Workspace saat ini: {name}"
  ],
  "工作区设置": [
    "Workspace settings",
    "Pengaturan workspace"
  ],
  "账号与工作区": [
    "Account & workspace",
    "Akun & workspace"
  ]
};
