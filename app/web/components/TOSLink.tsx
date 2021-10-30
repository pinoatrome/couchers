import { TERMS_OF_SERVICE } from "features/auth/constants";
import Link from "next/link";
import { tosRoute } from "routes";
import makeStyles from "utils/makeStyles";

const useStyles = makeStyles((theme) => ({
  root: {
    color: theme.palette.primary.main,
    textDecoration: "underline",
  },
}));

export default function TOSLink() {
  const classes = useStyles();
  return (
    <Link href={tosRoute}>
      <a target="_blank" className={classes.root}>
        {TERMS_OF_SERVICE}
      </a>
    </Link>
  );
}
