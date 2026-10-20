import { useEffect, useState } from "react";
import Icon, { RelayMark } from "../components/Icon";
import LanguageSelect from "../components/LanguageSelect";
import BlogHeader from "./BlogHeader";
import { t } from "../i18n";
import { useLocale } from "../useLocale";
import "./blog.css";

interface Post {
  slug: string;
  title: string;
  description: string;
  language: string;
  publishedAt: string | null;
  href: string;
  cover: string | null;
}

function ArticleCard({ post, featured = false }: { post: Post; featured?: boolean }) {
  return (
    <a className={`blog-card ${featured ? "blog-card-featured" : ""}`} href={post.href} aria-labelledby={`title-${post.slug}`}>
      <article>
        <div className="blog-card-meta">
          <span><Icon name="doc" size={18} />{t("blogArticle")}</span>
          {post.publishedAt && <time dateTime={post.publishedAt}>{post.publishedAt}</time>}
        </div>
        <div className="blog-card-body">
          <div className="blog-card-copy" lang={post.language}>
            <h2 id={`title-${post.slug}`}>{post.title}</h2>
            <p>{post.description}</p>
          </div>
          {post.cover && <div className="blog-card-image"><img src={post.cover} alt="" loading={featured ? "eager" : "lazy"} /></div>}
        </div>
        <div className="blog-card-foot"><span><RelayMark size={16} />Relay</span><Icon name="external" size={19} /></div>
      </article>
    </a>
  );
}

export default function Blog() {
  useLocale();
  const [posts, setPosts] = useState<Post[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { document.title = "Blog · Relay"; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    void fetch("/api/blog", { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error("Unable to load articles");
        return response.json() as Promise<Post[]>;
      })
      .then(setPosts)
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [attempt]);

  return (
    <div className="blog-site">
      <BlogHeader />
      <main className="blog-container">
        <div className="blog-intro">
          <h1>{t("blogArticles")}</h1>
          <p>{t("blogIntro")}</p>
        </div>
        {error ? (
          <div className="blog-status" role="alert">
            <p>{t("blogLoadError")}</p>
            <button className="btn secondary" onClick={() => setAttempt(value => value + 1)}>{t("retry")}</button>
          </div>
        ) : posts === null ? (
          <p className="blog-status" role="status">{t("loading")}</p>
        ) : posts.length === 0 ? (
          <p className="blog-status">{t("blogEmpty")}</p>
        ) : (
          <section className="blog-articles" aria-label={t("blogArticles")}>
            <div className="blog-feature"><ArticleCard post={posts[0]} featured /></div>
            {posts.length > 1 && (
              <div className="blog-grid">{posts.slice(1).map(post => <ArticleCard post={post} key={post.slug} />)}</div>
            )}
          </section>
        )}
      </main>
      <footer className="blog-footer">
        <div className="blog-container">
          <a className="blog-brand" href="/"><RelayMark size={22} /><span>Relay</span></a>
          <LanguageSelect />
        </div>
      </footer>
    </div>
  );
}
